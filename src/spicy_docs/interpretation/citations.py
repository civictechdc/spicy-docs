"""What one document's text cites, as named rules over the normalized text.

Reads the parser-ready text of one document
(``extraction.body_text.rendition_text``'s ``BodyText``), its per-page split
where the rendition carries one, and -- for the committee rule alone -- the
chamber rosters this repository already reads, and returns one
:class:`CitationFinding` per occurrence naming the kind, the rule and its
version, the canonical target key in the hosted table's own spelling, the
exact text that matched, and the character offsets and printed page where it
was read. Seven kinds are read by the stack's one data-side grammar and keyed
from what it parsed: U.S. Code sections, CFR parts and sections, Public Laws,
Statutes at Large pages and Federal Register cites by
:mod:`spicy_docs.interpretation.citation_grammar`, RINs and agency dockets by
:mod:`spicy_docs.interpretation.identifier_shapes`. The rest are patterns
measured and lifted unchanged from the 2026-09-20 rollup. Every rule carries the lookalikes it must reject, asserted in
``tests/test_citations.py`` so a rule that widened into prose fails a check
rather than raising a hit rate. The committee resolver takes the roster
vocabulary as an argument, so this module stays pure: nothing fetches, reads a
file or a clock.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from spicy_docs.interpretation import citation_grammar
from spicy_docs.interpretation.identifier_shapes import (
    IdentifierCandidate,
    IdentifierKind,
    detect_identifier_shapes,
    normalize_docket_reference,
    published_rin,
)
from spicy_docs.schemas.tables import natural_key


class CitationError(ValueError):
    """The text and the page split handed to a rule do not describe one document."""


# --- canonical forms -----------------------------------------------------------------


def canonical_alnum(value: str) -> str:
    """``H.R. 7806``, ``HR 7806`` and a wrapped ``H.R.\\n7806`` are one key."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


#: The bill-type vocabulary, longest spelling first so ``SRES21`` is a Senate
#: resolution and not Senate bill ``S`` numbered ``RES21``.  Same eight names
#: ``sources.congress.bill_status.BILL_TYPES`` holds; spelled here in match
#: order because that order is what makes the split correct.
BILL_TYPES_BY_LENGTH: tuple[str, ...] = ("hconres", "sconres", "hjres", "sjres", "hres", "sres", "hr", "s")

MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

#: A bill designator, then a separator, then the number.  Both halves were
#: re-derived from measured false positives (module docstring).  The first
#: guard refuses a designator right after a letter and a period -- ``U.S.``,
#: and since 002 ``R.S. 2477`` (a Revised Statutes section) and ``W.S.
#: 11-6-302`` (Wyoming's), which read as Senate bills. It is the guard
#: ``release_matching``'s own alternation carried when this rule replaced it
#: (consolidation item A9): over the survey's 143,964 retained texts it
#: removed those 9 matches and no other.
CONGRESS_CHAMBER = (
    r"(?<![A-Za-z]\.)(?<!U\.\s)(?<![A-Za-z])"
    r"(?:H\.?\s?R|H\.?\s?J\.?\s?Res|H\.?\s?Con\.?\s?Res|H\.?\s?Res"
    r"|S\.?\s?J\.?\s?Res|S\.?\s?Con\.?\s?Res|S\.?\s?Res|S)"
)

#: What may follow a bill number, since ``bill_number`` 003. Two refusals,
#: each the only reading of its shape in the retained corpora -- the 40
#: activity reports, the audit's five budget volumes and the parsing survey's
#: 143,964 bill and 60,000 Federal Register texts, 31,955 matches of the 002
#: rule (receipt ``fix-print-citations-2026-09-26/``):
#:
#: * a parenthesized subdivision attached to the number is a provision, not a
#:   measure. ``CLAUSE S 2(N), (O), OR (P) OF RULE XI`` (a spaced-out
#:   ``CLAUSES``, CRPT-117hrpt702) read as Senate bill 2; the two matches it
#:   removes are the only ones followed by ``(``;
#: * a year opening a line and closing with a colon is a heading. ``S. Con.
#:   Res.\n2022:`` (CRPT-117hrpt708, whose contents lost the ``14``) read as a
#:   concurrent resolution numbered 2022; the seven other year-shaped numbers
#:   wrapped onto a line of their own (``H.R.\n2021``) are real bills and none
#:   closes with a colon, while an unwrapped ``H.R. 7593: Modernizing ...``
#:   (CRPT-118hrpt964) still reads.
BILL_NUMBER_END = r"\b(?!\()(?!(?<=\n(?:19|20)\d\d):)"


# --- the committee vocabulary and the resolver ---------------------------------------


#: The chambers a committee print can belong to, and so the chambers a
#: vocabulary can be read for.
COMMITTEE_CHAMBERS: tuple[str, ...] = ("house", "senate")

#: A chamber the print names immediately before a committee name: ``Senate
#: Committee on Armed Services``, ``the House Committee on the Budget``. Read
#: since ``committee_name`` 002, and such a name resolves among that chamber's
#: committees only: before it, Senate-named names published House codes --
#: the 11 shared names, and 24 ``Senate Committee on Homeland Security`` (a
#: wrapped ``... and Governmental Affairs``) as ``hshm00`` (``docs/decisions.md``,
#: receipt ``fix-print-citations-2026-09-26/replay-qualified.json``). Case as
#: printed: the candidate rule itself reads only ``Committee on``.
NAMED_CHAMBER = re.compile(r"\b(House|Senate)\s+$")

#: How far before a committee name :data:`NAMED_CHAMBER` looks: the longer
#: word, and the whitespace or line break a wrapped cover sets after it.
_NAMED_CHAMBER_REACH = len("Senate") + 4


def named_chamber(text: str, start: int) -> str | None:
    """``house`` or ``senate`` when the print names that chamber right before offset ``start``, else ``None``."""
    named = NAMED_CHAMBER.search(text, max(0, start - _NAMED_CHAMBER_REACH), start)
    return None if named is None else named.group(1).lower()


def committee_vocabulary(
    *, house: Iterable[object] = (), senate: Iterable[object] = (), chamber: str, own_only: bool = False
) -> tuple[tuple[str, str], ...]:
    """``(canonical name, system_code)`` for every committee the given rosters state, read for one chamber's print.

    Takes what the readers in ``sources/congress/committee_rosters.py`` already
    produced -- ``HouseMemberData`` records for ``house``, ``SenateCvc``
    records for ``senate`` -- and reads them structurally, so this module stays
    pure. The Senate ``cvc`` file states only the committees its listed
    senators sit on, so that side is a floor and a name it does not reach stays
    unresolved rather than being guessed at.

    ``chamber`` is the chamber whose committee wrote the print, and it decides
    a name both chambers hold: *Committee on the Judiciary* in a Senate report
    is the Senate's (``ssju00``), in a House report the House's. It is required
    because until 2026-09-26 the House silently won every such name, and the
    two Senate Judiciary reports published ``hsju00`` for their own committee
    1,717 times (see ``docs/decisions.md``). A name only one chamber holds
    resolves to it whichever chamber reads -- unless ``own_only``, which keeps
    ``chamber``'s committees alone: the vocabulary for a name the print
    qualifies with that chamber (:data:`NAMED_CHAMBER`), where the other
    chamber's committee cannot be meant.
    """
    if chamber not in COMMITTEE_CHAMBERS:
        raise CitationError(f"chamber must be one of {', '.join(COMMITTEE_CHAMBERS)}, not {chamber!r}")
    by_chamber: dict[str, list[tuple[str, str]]] = {
        "house": [
            (
                canonical_alnum(committee.name),
                getattr(committee, "system_code", None) or "hs" + str(committee.code).lower(),
            )
            for roster in house
            for committee in getattr(roster, "committees", ())
        ],
        "senate": [
            (canonical_alnum(assignment.name), assignment.system_code)
            for roster in senate
            for senator in getattr(roster, "senators", ())
            for assignment in getattr(senator, "committees", ())
        ],
    }
    entries: dict[str, str] = {}
    others = () if own_only else tuple(other for other in COMMITTEE_CHAMBERS if other != chamber)
    for side in (chamber, *others):
        for name, code in by_chamber[side]:
            entries.setdefault(name, code)
    return tuple(sorted(entries.items()))


#: The routes :func:`resolve_committee_names` settles a candidate by, in the
#: order it tries them.  ``exact`` and ``roster_prefix`` are lookups against
#: the supplied vocabulary; ``name_prefix`` and ``sibling_prefix`` are
#: *inferences* from the printed text, which is why the route is reported and
#: a consumer wanting only lookups can filter on it.
COMMITTEE_ROUTES: tuple[str, ...] = ("exact", "roster_prefix", "name_prefix", "sibling_prefix", "unresolved")

#: Tokens that join two halves of a committee's name.  A remainder containing
#: one means the candidate is a *longer committee's* name and not a roster
#: name with prose after it, so route 3 must refuse it.
_NAME_JOINING_TOKENS: tuple[str, ...] = ("AND",)

#: The shortest fragment route 4 will settle.  ``COMMITTEEON`` plus four
#: characters: below that a fragment is a line-wrap stub that happens to
#: prefix one sibling, and ``COMMITTEEONA`` resolving to Appropriations is the
#: measured case this refuses.
_MIN_SIBLING_FRAGMENT = len("COMMITTEEON") + 4


@dataclass(frozen=True, slots=True)
class CommitteeResolution:
    """One printed candidate's outcome: the code, and which route reached it."""

    system_code: str | None
    route: str


def _joins_a_longer_name(remainder: str) -> bool:
    """Does what follows a matched roster name continue that name, or start prose?

    ``COMMITTEEONWAYSANDMEANS`` + ``REPUB`` is the roster name running into a
    chairman's party, while ``COMMITTEEONHOMELANDSECURITY`` +
    ``ANDGOVERNMENTALAFFAIRS`` is the Senate's *longer* committee that merely
    starts with the House's name -- resolving that one to the House code was a
    plausible, published, unflagged wrong join.
    """
    return any(remainder.startswith(token) for token in _NAME_JOINING_TOKENS)


def resolve_committee_names(
    values: Iterable[str], vocabulary: Sequence[tuple[str, str]]
) -> dict[str, CommitteeResolution]:
    """Settle each printed candidate against the rosters, or leave it unresolved.

    Four routes, in order, each a statement about the print rather than a guess
    and each reported by name on the result:

    1. ``exact`` -- the candidate *is* a roster name.
    2. ``roster_prefix`` -- the candidate is a line-wrapped prefix of exactly
       one roster name (``Committee on Natural Re``).
    3. ``name_prefix`` -- a roster name is a prefix of the candidate, which is
       that name running into following prose. **Refused when the remainder
       begins a name-joining token**, because the Senate's ``Committee on
       Homeland Security and Governmental Affairs`` starts with a House
       committee's whole name and this route published the House code for it.
    4. ``sibling_prefix`` -- the candidate is a prefix of other candidates in
       the same document that all resolved to one committee, which is how
       ``Committee on Agri`` settles where the roster alone cannot. A fragment
       shorter than ``Committee on`` plus four characters is refused, because
       ``Committee on A`` would otherwise take whichever single sibling shared
       its first letter.

    A candidate that stays ambiguous, and every committee no supplied roster
    names, is ``unresolved`` rather than counted; ``O(V * (R + V))``.
    """
    resolved: dict[str, CommitteeResolution] = {}
    for value in values:
        exact = [code for name, code in vocabulary if name == value]
        if exact:
            resolved[value] = CommitteeResolution(exact[0], "exact")
            continue
        prefixed = {code for name, code in vocabulary if name.startswith(value)}
        if len(prefixed) == 1:
            resolved[value] = CommitteeResolution(prefixed.pop(), "roster_prefix")
            continue
        contains = sorted(
            (
                (name, code)
                for name, code in vocabulary
                if value.startswith(name) and not _joins_a_longer_name(value[len(name) :])
            ),
            key=lambda pair: -len(pair[0]),
        )
        resolved[value] = (
            CommitteeResolution(contains[0][1], "name_prefix") if contains else CommitteeResolution(None, "unresolved")
        )
    for value, outcome in list(resolved.items()):
        if outcome.system_code is not None or len(value) < _MIN_SIBLING_FRAGMENT:
            continue
        siblings = {
            other.system_code
            for name, other in resolved.items()
            if other.system_code is not None and name.startswith(value)
        }
        if len(siblings) == 1:
            resolved[value] = CommitteeResolution(siblings.pop(), "sibling_prefix")
    return resolved


# --- the rules -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationContext:
    """What a target key needs that the matched text alone does not state.

    ``congress`` is the Congress a bare bill designator belongs to: a print
    writes ``H.R. 7806`` and never the Congress beside it, so the caller
    supplies the one the document states it covers (for an activity report,
    ``sources.govinfo.activity_reports.covered_congress``), and a bill key is
    built only from a stated Congress -- with none, the finding keeps the
    printed form and says it is unresolved. ``committees`` is the ``{canonical candidate:
    CommitteeResolution}`` map :func:`resolve_committee_names` produced for this
    one document.
    """

    congress: int | None = None
    committees: Mapping[str, CommitteeResolution] = field(default_factory=dict)


#: ``(target key, whether the key is the hosted table's own spelling, the rule
#: that reached it)``.  The third part is the rule's own name for every kind
#: but ``committee_name``, where it is the resolution route.
type TargetReader = Callable[[str, CitationContext], tuple[str, bool, str]]


def _target_from_canonical(name: str, canonical: Callable[[str], str]) -> TargetReader:
    return lambda value, _context: (canonical(value), True, name)


_BILL_SPLIT = re.compile(r"([A-Z]+)(\d{1,5})$")


def bill_type_and_number(value: str) -> tuple[str, str] | None:
    """``H.R. 7806`` is ``("hr", "7806")``; anything outside the vocabulary is ``None``.

    The Congress-free half of a bill key, exposed because a consumer comparing
    a print against an index has to be able to compare without one.
    """
    split = _BILL_SPLIT.fullmatch(canonical_alnum(value))
    if split is None:
        return None
    letters, number = split.group(1).lower(), split.group(2)
    kind = next((name for name in BILL_TYPES_BY_LENGTH if letters == name), None)
    return None if kind is None else (kind, number)


def _bill_target(value: str, context: CitationContext) -> tuple[str, bool, str]:
    """``H.R. 7806`` in a 118th-Congress document is ``118-hr-7806``.

    **The Congress is the document's statement, and a bounded one**: every
    bare designator is stamped with the Congress the caller read from the
    document, so an activity report that discusses an earlier Congress's law
    still publishes a ``bill_id`` for the wrong Congress with
    ``target_resolved`` true -- which is why ``house_activity_reports`` carries
    ``bills_congress_mismatch``. Without a stated Congress the canonical
    printed form stands and the finding says the key is not the catalog's; the
    type/number split runs longest-name-first so ``S. Res. 21`` is ``sres`` and
    not ``s``.
    """
    parts = bill_type_and_number(value)
    if parts is None or context.congress is None:
        return canonical_alnum(value), False, "bill_number"
    return natural_key(context.congress, *parts), True, "bill_number"


_DOCKET_PARTS = re.compile(r"(\d{2})[-–](\d{1,4})")
_US_REPORTS_PARTS = re.compile(r"(\d{1,3})\s+U\.\s?S\.\s+(\d{1,4})")


def _two_part_target(name: str, pattern: re.Pattern[str]) -> TargetReader:
    """``{first}-{second}`` from a two-part cite, or the printed form unresolved."""

    def read(value: str, _context: CitationContext) -> tuple[str, bool, str]:
        parts = pattern.search(value)
        if parts is None:
            return canonical_alnum(value), False, name
        return f"{parts.group(1)}-{parts.group(2)}", True, name

    read.__name__ = f"two_part_{name}"
    return read


def _printed_id_target(name: str) -> TargetReader:
    """The identifier exactly as its publisher spells it, upper-cased.

    The canonical form the *measurement* compares on strips the separators
    (``GAO24106221``), while the key a consumer joins on keeps them
    (``gao/files.py``'s selection key and ``dockets.docket_id`` are both the
    hyphenated form); an en-dash a print sets becomes the hyphen the publisher
    uses.
    """

    def read(value: str, _context: CitationContext) -> tuple[str, bool, str]:
        return value.strip().upper().replace("–", "-"), True, name

    read.__name__ = f"printed_id_{name}"
    return read


def _committee_target(value: str, context: CitationContext) -> tuple[str, bool, str]:
    """The ``system_code`` a roster settled this candidate to, or the candidate itself.

    An unresolved candidate is still stored, keyed on its own canonical printed
    form: it is evidence only the print holds, and dropping it would lose the
    committee this repository's pinned rosters happen not to reach. The row
    says which it is, so a consumer joining ``committees.system_code`` filters
    on one column instead of guessing from the key's shape.
    """
    canonical = canonical_alnum(value)
    outcome = context.committees.get(canonical) or CommitteeResolution(None, "unresolved")
    if outcome.system_code is None:
        return canonical, False, outcome.route
    return outcome.system_code, True, outcome.route


#: One occurrence a grammar-read rule found: ``(span_start, span_end, target
#: key, whether the key is the hosted table's own spelling)``.
type GrammarHit = tuple[int, int, str, bool]

#: How a grammar-read rule reads one whole text: every occurrence, in order.
#: "The grammar" is the pair of modules the stack shares -- ``citation_grammar``
#: and ``identifier_shapes`` -- and a change inside either moves no pattern
#: here, which is why ``tests/test_citations.py`` pins what the readers say
#: over the committed fixtures as well as what they are called.
type GrammarReader = Callable[[str], Iterator[GrammarHit]]

#: The grammar's refusals that leave a key's coordinates as printed: each is
#: about the cite's *scope* -- ``et seq.``, a note, a subpart pairing, a range
#: end it could not read -- and not about the title, part or section the key
#: is built from. An allowlist on purpose: any other refusal, including one
#: the grammar gains later, publishes its key unresolved.
_SCOPE_ONLY_REFUSALS: frozenset[str | None] = frozenset(
    {
        None,
        "open_ended_reference_unresolved",
        "note_target_unresolved",
        "ambiguous_part_scope",
        "range_end_unread",
        "usc_open_ended_reference_unresolved",
        "usc_note_position_unresolved",
    }
)


def _usc_section_hits(text: str) -> Iterator[GrammarHit]:
    """``42 U.S.C. 7401-7671q`` is ``42-7401`` and ``42-7671q``: a range is its two endpoints, on one span.

    The key is ``{title}-{section}`` in the grammar's section spelling --
    lower-cased, with subsection detail, trailing punctuation and zero pads
    left off -- and an appendix title carries the ``A`` ``law_code_sections``
    spells it with (``50A-2401``). A chapter names no section and is not read.
    Unresolved where the grammar refuses the coordinates themselves, where a
    list member was reached past a Statutes cite (the grammar cannot tell a
    resumed section from that law's own page), and at the end of an
    *abbreviated* span such as ``1484-86``, which the grammar expanded rather
    than read. A hyphen the grammar cannot order stays one token
    (``4801-4582``), as the grammar keeps it.
    """
    for occurrence in citation_grammar.find_usc_citations(text):
        citation = occurrence.citation
        # The occurrence retains damaged source text, but its readable prefix
        # names a different section ("2151p1" must not link to "2151p").
        if occurrence.refusal == "usc_coordinate_continuation_unresolved":
            continue
        if citation.authority_type != "usc" or citation.usc_title is None or citation.usc_section is None:
            continue
        title = f"{citation.usc_title}{'A' if citation.usc_appendix else ''}"
        trusted = occurrence.refusal in _SCOPE_ONLY_REFUSALS and not citation.usc_section_after_statute
        yield occurrence.start, occurrence.end, f"{title}-{citation.usc_section}", trusted
        if citation.usc_section_end is not None:
            stated = citation.usc_section_span_rule == citation_grammar.USC_SPAN_STATED
            yield occurrence.start, occurrence.end, f"{title}-{citation.usc_section_end}", trusted and stated


def _cfr_section_hits(text: str) -> Iterator[GrammarHit]:
    """``40 CFR part 60`` is ``40-60`` and ``40 CFR 60.5`` is ``40-60.5``: a section is spelled with its part.

    Every case of the part label reads (``part``, ``Part``, ``Parts``,
    ``PART``), a plural label's list is one key per part, and a ``through``
    range is its two endpoints on one span. A *hyphen* between two numbers is
    not split: the grammar refuses it as ambiguous, because real section
    numbers carry one (``46 CFR 1.01-15``), so ``40 CFR Part 1500-1508`` keeps
    the printed token and is unresolved. Unresolved too where the title cannot
    exist or the part's digit run is longer than any real part's. A title with
    no part (``40 CFR``) names nothing and is not read. A subpart-letter list
    names its part once: the link table has no subpart key. The grammar still
    retains the complete qualifier text and any ambiguity verdict.
    """
    for occurrence in citation_grammar.find_cfr_citations(text, expand_qualifiers=False):
        citation = occurrence.citation
        endpoints = (
            (citation.start, citation.end) if isinstance(citation, citation_grammar.CfrCitationRange) else (citation,)
        )
        trusted = occurrence.refusal in _SCOPE_ONLY_REFUSALS
        for endpoint in endpoints:
            if endpoint.cfr_part is None:
                continue
            section = f".{endpoint.cfr_section}" if endpoint.cfr_section else ""
            plausible = endpoint.title_is_possible and endpoint.part_is_plausible is not False
            yield (
                occurrence.start,
                occurrence.end,
                f"{endpoint.cfr_title}-{endpoint.cfr_part}{section}",
                trusted and plausible,
            )


def _public_law_hits(text: str) -> Iterator[GrammarHit]:
    """``Pub. L. No. 118-31`` is ``118-public-31``: the ``laws`` identity, joined, with integer parts.

    Always ``public``: the grammar reads only the public spellings, and the
    Congress comes from the cite itself. Unresolved below the first Congress
    whose laws are numbered (the 57th), where the print's number is damage
    (``Pub. L. 04-13``) rather than a law.
    """
    for occurrence in citation_grammar.find_public_law_citations(text):
        congress, _, number = str(occurrence.citation.public_law).partition("-")
        numbered = int(congress) >= citation_grammar.PL_FIRST_NUMBERED_CONGRESS
        yield occurrence.start, occurrence.end, natural_key(congress, "public", number), numbered


def _statutes_hits(text: str) -> Iterator[GrammarHit]:
    """``136 Stat. 1234`` is ``136-1234``: ``{volume}-{page}``, with a lettered volume or page kept whole.

    ``70A Stat. 157`` is ``70A-157`` and ``113 Stat. 1501A-293`` is
    ``113-1501A-293``; a range of lettered pages is its two pages on one span.
    Unresolved where the volume cannot carry a law of the Public Law printed
    beside it -- one of the two is damaged, and nothing here says which.
    """
    for occurrence in citation_grammar.find_statute_citations(text):
        citation = occurrence.citation
        volume = citation.statute_volume_text or citation.statute_volume
        pages = citation.statute_page_text.split(" to ") if citation.statute_page_text else [str(citation.statute_page)]
        consistent = citation.statute_volume_matches_public_law is not False
        for page in pages:
            yield occurrence.start, occurrence.end, f"{volume}-{page}", consistent


def _federal_register_hits(text: str) -> Iterator[GrammarHit]:
    """``89 FR 12345`` and ``88 Fed. Reg. 12,345`` are ``{volume}-{page}``, the pair the host resolves.

    The Register's own ``FR`` spelling reads, which the 001 pattern -- the
    Bluebook ``Fed. Reg.`` alone -- did not; a thousands comma is the page's.
    """
    for occurrence in citation_grammar.find_federal_register_citations(text):
        citation = occurrence.citation
        yield occurrence.start, occurrence.end, f"{citation.volume}-{citation.page}", True


@lru_cache(maxsize=1)
def _identifiers_in(text: str) -> tuple[IdentifierCandidate, ...]:
    """The prose detector's reading of one text, kept for the next rule that asks.

    Two rules read the same detection -- ``rin`` and ``docket_number`` -- and it
    was a fifth of a whole document's reading time done twice. One entry: the
    last text read is held until the next one replaces it.
    """
    return tuple(detect_identifier_shapes(text))


#: A label that says the number after it is an OMB control number, which a
#: FEMA collection can shape like a RIN ("OMB Number: 1660-NW32"): 2 of the 21
#: RINs the identifier detector read that the 002 labelled rule did not, in the
#: parsing survey's Federal Register texts.
_OMB_NUMBER_LABEL = re.compile(r"\bOMB\s+(?:control\s+)?(?:numbers?|nos?\.?|#)\s*[:#]?\s*$", re.IGNORECASE)


def _identifier_reader(
    kind: IdentifierKind, key: Callable[[str], str | None], *, refused_after: re.Pattern[str] | None = None
) -> GrammarReader:
    """Every identifier of ``kind`` the prose detector finds, keyed by ``key``; a value it cannot key is not read.

    The detector arbitrates overlaps -- a docket inside a Regulations.gov
    document id is the document's -- and its spans index the text as printed.
    ``refused_after`` is a label that, ending right before a candidate, says
    the candidate is another system's number.
    """

    def read(text: str) -> Iterator[GrammarHit]:
        for candidate in _identifiers_in(text):
            start, end = candidate.span
            if candidate.kind is not kind or (value := key(candidate.value)) is None:
                continue
            if refused_after is not None and refused_after.search(text, max(0, start - 40), start):
                continue
            yield start, end, value, True

    read.__name__ = f"identifier_shapes_{kind.value}"
    return read


@dataclass(frozen=True, slots=True)
class CitationRule:
    """One measured extraction rule, what it joins to, and what it must reject.

    A rule is read one of two ways, and exactly one. A ``pattern`` carries no
    capturing group, so one match is one string on every reader (a test holds
    it to that); a rule that needs the match's parts reads them in its own
    ``target`` with a second, local pattern, which keeps the measured pattern
    byte-identical to what was measured. A ``reader`` is the citation grammar:
    it reads the whole text and states each occurrence's span and key itself,
    because what it recognises -- lists, ranges, reversed ``part 60 of title
    40`` forms -- is not one match of one pattern. ``index_pattern`` exists
    because the two sides spell the same fact differently and both sides
    reduce to ``canonical`` before the rollup tool compares them, so a key the
    index already states is never counted as something only the document
    holds. ``version`` moves when the pattern or reader, the rejects or the
    target reader changes, and is a zero-padded decimal because a merge orders
    this column as a string.
    """

    name: str
    version: str
    target_table: str
    target_key_shape: str
    pattern: str | None = None
    #: The citation grammar's reading of this kind, for a rule it reads.
    reader: GrammarReader | None = None
    rejects: tuple[str, ...] = ()
    note: str = ""
    #: How the *index* spells this key, when that differs from the print.
    index_pattern: str | None = None
    #: Both sides are reduced to this form before being compared.
    canonical: Callable[[str], str] = canonical_alnum
    #: The hosted key one match names.  Defaults to ``canonical``.
    target: TargetReader | None = None

    def __post_init__(self) -> None:
        if (self.pattern is None) == (self.reader is None):
            raise CitationError(f"{self.name}: a rule is read by a pattern or by the grammar, and by exactly one")

    @property
    def source(self) -> str:
        """What reads this rule: its pattern, or the name of the grammar reader."""
        return self.pattern if self.reader is None else f"reader:{self.reader.__name__}"

    def compiled(self) -> re.Pattern[str]:
        if self.pattern is None:
            raise CitationError(f"{self.name} is read by the citation grammar, not by a pattern")
        return re.compile(self.pattern)

    def compiled_index(self) -> re.Pattern[str]:
        return re.compile(self.index_pattern) if self.index_pattern else self.compiled()

    def reads(self, text: str) -> bool:
        """Whether this rule finds anything at all in ``text`` -- what a reject must never do."""
        if self.reader is not None:
            return next(self.reader(text), None) is not None
        return self.compiled().search(text) is not None

    def target_key(self, matched: str, context: CitationContext) -> tuple[str, bool, str]:
        reader = self.target or _target_from_canonical(self.name, self.canonical)
        return reader(matched, context)


CITATION_RULES: tuple[CitationRule, ...] = (
    CitationRule(
        name="bill_number",
        version="003",
        pattern=rf"{CONGRESS_CHAMBER}[.\s]\s?\d{{1,5}}{BILL_NUMBER_END}",
        target_table="congress_bills",
        target_key_shape="bill_id: {congress}-{bill_type}-{number}, from the caller's stated Congress",
        rejects=(
            "HR department",
            "S. Smith",
            "H. R.",
            "Res. 2024 budget",
            "600 U. S. 183",
            "603 U.S. 25",
            "HR974",
            "S4601",
            "ANALYSIS. 12",
            "R.S. 2477",
            "W.S. 11-6-302",
            "CLAUSE S 2(N), (O), OR (P) OF RULE XI",
            "S. Con. Res.\n2022:",
        ),
        note="chamber designator plus number; the Congress must come from the document's own statement of it",
        target=_bill_target,
    ),
    # The four kinds below have been read by the citation grammar since their
    # 002 (2026-09-23, consolidation items B4 and A10). Their 001 patterns
    # published keys that do not parse back -- a trailing ``.`` or ``-``, an
    # en dash, a U.S.C. range as one token, a zero-padded law number -- all
    # with ``target_resolved`` true, and read only lower-case singular
    # ``part``; see ``docs/research/parsing-survey-2026-09-23.md`` section 2.
    CitationRule(
        name="public_law",
        version="003",
        reader=_public_law_hits,
        target_table="laws",
        target_key_shape="(congress, law_type, number), joined: {congress}-public-{number}",
        rejects=("Public Lands", "P.L. Smith", "Pub L", "Republic Law 5", "Pub. L. Rev."),
        note=(
            "001 read four spellings with one pattern; the grammar also reads a space after the dash "
            "('Public Law 92- 463') and a dotted separator, and does not read a zero-padded number"
        ),
    ),
    CitationRule(
        name="statutes_at_large",
        version="002",
        reader=_statutes_hits,
        target_table="laws",
        target_key_shape="statutes_at_large_cite as {volume}-{page}; a lettered volume or page kept whole",
        rejects=("Stat. of the Union", "12 State 45"),
        note="001 required a period and a space ('86 Stat.770' and '116 Stat 2962' went unread)",
    ),
    CitationRule(
        name="usc_section",
        version="003",
        reader=_usc_section_hits,
        target_table="law_code_sections",
        target_key_shape="{usc_title}-{usc_section}; an appendix title as {title}A; a range as its two endpoints",
        rejects=("U.S. Code of conduct", "42 USC for", "42 U.S.C. chapter 85"),
    ),
    CitationRule(
        name="cfr_section",
        version="003",
        reader=_cfr_section_hits,
        target_table="cfr sections (host-side)",
        target_key_shape="{title}-{part}, or {title}-{part}.{section} where a section is cited",
        rejects=("CFR is the", "40 CRF 60", "A40 CFR 60", "3 CFR, 1977 Comp., p. 123"),
    ),
    # Three more read through the grammar modules since 2026-09-23, each
    # moving its version: 001 of ``federal_register_cite`` read only the
    # Bluebook ``Fed. Reg.`` and missed the Register's own ``89 FR 12345``;
    # 002 of ``docket_number`` cut ``EPA-HQ-OAR-2004-0015`` to
    # ``OAR-2004-0015`` and read ITC investigations (``731-TA-1199-1200``) as
    # dockets; 002 of ``rin`` kept its own copy of the RIN shape and needed
    # the ``RIN`` label, so a list (``RINs 1018-AU04, 1018-AU09``) gave its
    # first member only.
    CitationRule(
        name="federal_register_cite",
        version="002",
        reader=_federal_register_hits,
        target_table="federal_register",
        target_key_shape="{volume}-{start_page}; the host resolves document_number by that pair",
        rejects=("Fed. Reg. of the", "88 Federal agencies", "88 fr 123", "76 R 11462"),
    ),
    CitationRule(
        name="rin",
        version="004",
        reader=_identifier_reader(IdentifierKind.RIN, published_rin, refused_after=_OMB_NUMBER_LABEL),
        target_table="federal_register",
        target_key_shape="the bare RIN, as regulation_id_numbers_json spells it: identifier_shapes.PUBLISHED_RIN",
        # A RIN-shaped damage or placeholder is detected and never keyed.
        rejects=("RIN of the", "RIN 1234", "RIN 1625-AAOO", "RIN 2060-XXXX", "OMB Number: 1660-NW32"),
        note=(
            "87 distinct RINs across the eight House activity reports and none in any CRPT MODS: "
            "the family's largest single citation yield, and invisible to a 60-page read"
        ),
    ),
    CitationRule(
        name="gao_product_id",
        version="001",
        pattern=r"\bGAO[-–]\d{2}[-–]\d{3,6}(?:[A-Z]{1,3})?\b",
        target_table="gao products (not hosted; gao/files.py selection key)",
        target_key_shape="product_id as GAO-YY-NNNNN",
        rejects=("GAO reported", "GAO-2026"),
        target=_printed_id_target("gao_product_id"),
    ),
    CitationRule(
        name="crs_report_id",
        version="001",
        pattern=r"\b(?:R|RL|RS|IF|IN|LSB|IG|MM)\d{4,6}\b",
        target_table="crs reports (Congress.gov crsreport)",
        target_key_shape="report_id as the publisher spells it",
        rejects=("R 1234", "RL-31312"),
    ),
    CitationRule(
        name="bioguide_id",
        version="001",
        pattern=r"\b[A-Z]\d{6}\b",
        target_table="members",
        target_key_shape="bioguide_id",
        rejects=("A 000375", "AB000375"),
        note=(
            "measured zero across all ten families: a bioguide id is an identifier the publishers assign "
            "and do not print, so this rule states a negative result rather than reaching a key"
        ),
    ),
    CitationRule(
        name="docket_number",
        version="003",
        reader=_identifier_reader(IdentifierKind.DOCKET, normalize_docket_reference),
        target_table="dockets",
        target_key_shape="docket_id as Regulations.gov spells it: identifier_shapes.normalize_docket_reference",
        rejects=("FAA 2016 6907", "ABC-16-0001", "731-TA-1199-1200", "MM Docket No. 98-213", "ER00-2089-000"),
        note="38 distinct agency dockets across the eight House activity reports; no CRPT MODS states one",
    ),
    CitationRule(
        name="case_docket_number",
        version="001",
        # Not preceded by ``L.``: ``Pub. L. No. 89-136`` is a public law, and the
        # first rule read it as a circuit docket in the GAO sample.
        pattern=r"(?<!L\.)(?<!L\. )\bNo\.\s?\d{2}[-–]\d{1,4}\b",
        target_table="courtlistener clusters (not hosted)",
        target_key_shape="docket_number as {term}-{sequence}",
        rejects=("No. 25", "Number 24-1001", "Pub. L. No. 89-136", "P.L. No. 89-136"),
        note=(
            "any federal case number printed in this shape, not only a Supreme Court docket: "
            "a GAO report cites circuit and district dockets the same way"
        ),
        target=_two_part_target("case_docket_number", _DOCKET_PARTS),
    ),
    CitationRule(
        name="us_reports_cite",
        version="002",
        pattern=r"\b\d{1,3}\s+U\.\s?S\.\s+\d{1,4}\b",
        target_table="court_citations",
        target_key_shape="citation as {volume}-{page}; the court_citations row with reporter 'U.S.' names the cluster",
        rejects=("U.S. Government", "600 US 1"),
        target=_two_part_target("us_reports_cite", _US_REPORTS_PARTS),
    ),
    CitationRule(
        name="committee_name",
        version="002",
        # A *candidate* finder, not a committee. A committee report wraps the
        # name across lines and runs it into the following prose, so this rule
        # alone yielded 90 distinct values over the eight activity reports --
        # five of them dates (``Committee on June``), 46 line-wrap prefixes of
        # each other (``Committee on Agri`` / ``Committee on Agriculture``) and
        # several running into a chairman's name. A month is rejected here; the
        # rest is settled by ``resolve_committee_names`` against the chamber
        # rosters, and only a resolved ``system_code`` is a committee.
        pattern=(
            r"\bCommittee on (?:the )?(?!"
            + "|".join(MONTHS)
            + r")[A-Z][A-Za-z']+(?:[, ]{1,2}(?:and )?[A-Z][A-Za-z']+){0,5}"
        ),
        target_table="committees",
        target_key_shape="system_code, through the chamber rosters; the canonical printed name when none settles it",
        rejects=("committee on the matter", "Committee of the Whole", "Committee on June 5"),
        target=_committee_target,
    ),
    CitationRule(
        name="dollar_amount",
        version="001",
        pattern=r"\$[\d,]+(?:\.\d+)?(?:\s?(?:million|billion|trillion))?",
        target_table="financial_changes (shape); no hosted target yet",
        target_key_shape="the amount as printed, punctuation removed",
        rejects=("$ per", "USD 400"),
    ),
    CitationRule(
        name="fiscal_year",
        version="001",
        pattern=r"\b(?:FY|fiscal year)\s?\d{4}(?:[-–]\d{2,4})?\b",
        target_table="no hosted target yet",
        target_key_shape="the fiscal year as printed",
        rejects=("FY of", "fiscal years"),
    ),
)


CITATION_RULES_BY_NAME: Mapping[str, CitationRule] = {rule.name: rule for rule in CITATION_RULES}

#: The kinds ``document_citations`` stores: every rule that reaches a key some
#: table or publisher addresses.  Three of the sixteen are left out and each
#: for its own reason -- ``bioguide_id`` because no print states one (measured
#: zero across ten families; the *index* states it, and
#: ``house_activity_reports.submitted_by_bioguide_id`` carries that), and
#: ``dollar_amount`` and ``fiscal_year`` because they are quantities rather
#: than links and address nothing.
#:
#: ``rin`` and ``docket_number`` are stored because they are the activity
#: reports' largest real yield: the
#: [MODS re-check](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
#: found 87 distinct RINs and 38 agency dockets across the eight prints, none
#: of them in any CRPT MODS, where the bills and laws the rollup led with are
#: all already stated.
DOCUMENT_CITATION_KINDS: tuple[str, ...] = (
    "bill_number",
    "public_law",
    "statutes_at_large",
    "usc_section",
    "cfr_section",
    "federal_register_cite",
    "rin",
    "gao_product_id",
    "crs_report_id",
    "docket_number",
    "case_docket_number",
    "us_reports_cite",
    "committee_name",
)


def _rule_set_version(rules: Sequence[CitationRule]) -> str:
    """A digest over every rule's name, version, pattern or grammar reader **and rejects**.

    Derived, not written: editing a pattern moves this even when someone
    forgets to move that rule's own ``version``, and the pinned test then names
    both. The rejects are in the input because they are part of the rule -- a
    reject that is no longer asserted cannot fail -- and so is the target
    reader's name, because swapping which function builds the published key
    changes that key without touching the pattern. It cannot see a change
    *inside* a reader; that is what the per-rule ``version`` is for.
    """
    joined = "\n".join(
        f"{rule.name}|{rule.version}|{rule.source}|{'|'.join(rule.rejects)}"
        f"|{getattr(rule.target, '__name__', 'canonical')}"
        for rule in rules
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


#: The identity of the whole rule set, for a row that states which rules
#: produced a document's counts.
CITATION_RULE_SET_VERSION = _rule_set_version(CITATION_RULES)


# --- findings ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationFinding:
    """One occurrence of one cite, with where in the normalized text it was read.

    ``span_start`` and ``span_end`` are character offsets into the same text
    the rule ran over -- the normalized text a ``BodyText`` carries, never the
    publisher's bytes -- so a consumer holding that text can re-read the span.
    ``page`` is the printed page the match *starts* on, and is ``None`` for a
    rendition that states no page boundary; a match that straddles a boundary
    is attributed to the page it began on.
    """

    kind: str
    rule_version: str
    target_key: str
    target_table: str
    target_resolved: bool
    #: How this key was reached.  The rule's own name for every kind but
    #: ``committee_name``, where it is one of :data:`COMMITTEE_ROUTES`: the
    #: two roster lookups (``exact``, ``roster_prefix``) are a different kind
    #: of claim from the two inferences (``name_prefix``, ``sibling_prefix``),
    #: and a consumer wanting only lookups filters on this.
    target_rule: str
    matched_text: str
    span_start: int
    span_end: int
    page: int | None


def page_starts(pages: Sequence[str]) -> tuple[int, ...]:
    """The offset each page's text begins at in ``"\\n".join(pages)``."""
    offsets: list[int] = []
    cursor = 0
    for page in pages:
        offsets.append(cursor)
        cursor += len(page) + 1
    return tuple(offsets)


def find_citations(
    text: str,
    *,
    pages: Sequence[str] | None = None,
    kinds: Sequence[str] = DOCUMENT_CITATION_KINDS,
    congress: int | None = None,
    committees: Sequence[tuple[str, str]] = (),
    chamber_committees: Mapping[str, Sequence[tuple[str, str]]] | None = None,
) -> tuple[CitationFinding, ...]:
    """Every cite the named rules find in one document's normalized text.

    ``pages`` is that same text's per-page split and is proved against ``text``
    rather than trusted, because a page map that does not rejoin would
    attribute every span to the wrong page silently; ``None`` means every
    finding's page is NULL, the honest answer rather than page 1. ``congress``
    is what a bare bill designator belongs to (see :class:`CitationContext`)
    and ``committees`` is the roster vocabulary from
    :func:`committee_vocabulary`, read for the chamber whose print this is.
    ``chamber_committees`` is each chamber's own vocabulary
    (``committee_vocabulary(..., own_only=True)``), for a committee name the
    print qualifies with its chamber (:data:`NAMED_CHAMBER`): ``Senate
    Committee on Armed Services`` in a House report is the Senate's, and a
    Senate-named name no Senate committee reaches stays unresolved rather than
    taking the House's. A named chamber with no entry there resolves through
    ``committees`` like any other name. Findings come back in ``(kind, span)`` order,
    which is stable and independent of the rules' own order. Raises
    ``CitationError`` for non-string text, a page split that does not rejoin,
    or an unknown rule name.
    """
    if not isinstance(text, str):
        raise CitationError(f"text must be a string, not {type(text).__name__}")
    starts: tuple[int, ...] = ()
    if pages is not None:
        if "\n".join(pages) != text:
            raise CitationError("the page split does not rejoin to the text the rules run over")
        starts = page_starts(pages)
    unknown = [name for name in kinds if name not in CITATION_RULES_BY_NAME]
    if unknown:
        raise CitationError(f"no such citation rule: {', '.join(unknown)}")

    rules = [CITATION_RULES_BY_NAME[name] for name in kinds]
    matches: dict[str, list[tuple[str, int, int]]] = {
        rule.name: [(m.group(0), m.start(), m.end()) for m in rule.compiled().finditer(text)]
        for rule in rules
        if rule.reader is None
    }

    # A printed committee name is a candidate until a roster settles it, and it
    # is settled over the whole document at once: the sibling-prefix rule reads
    # the other candidates this document printed.
    candidates = sorted({canonical_alnum(value) for value, _, _ in matches.get("committee_name", ())})
    context = CitationContext(congress=congress, committees=resolve_committee_names(candidates, committees))
    # A name the print qualifies with a chamber is settled among that chamber's
    # committees, over the same candidates so its siblings still count; a name
    # with no chamber word before it reads exactly as before.
    named_contexts = {
        chamber: CitationContext(congress=congress, committees=resolve_committee_names(candidates, vocabulary))
        for chamber, vocabulary in (chamber_committees or {}).items()
        if candidates
    }

    def context_at(rule: CitationRule, start: int) -> CitationContext:
        if rule.name != "committee_name" or not named_contexts:
            return context
        return named_contexts.get(named_chamber(text, start) or "", context)

    findings: list[CitationFinding] = []
    for rule in rules:
        if rule.reader is None:
            hits = [
                (start, end, *rule.target_key(matched, context_at(rule, start)))
                for matched, start, end in matches[rule.name]
            ]
        else:
            hits = [(start, end, key, resolved, rule.name) for start, end, key, resolved in rule.reader(text)]
        # The table's identity is (kind, key, span start): the grammar can
        # reach one key at one offset twice -- two of its forms over one span
        # -- and that is one citation, not two.
        seen: set[tuple[str, int]] = set()
        for start, end, target, resolved, route in hits:
            if (target, start) in seen:
                continue
            seen.add((target, start))
            findings.append(
                CitationFinding(
                    kind=rule.name,
                    rule_version=rule.version,
                    target_key=target,
                    target_table=rule.target_table,
                    target_resolved=resolved,
                    target_rule=route,
                    matched_text=text[start:end],
                    span_start=start,
                    span_end=end,
                    page=None if not starts else bisect.bisect_right(starts, start),
                )
            )
    findings.sort(key=lambda finding: (finding.kind, finding.span_start, finding.target_key))
    return tuple(findings)


def rejected_lookalikes() -> dict[str, list[str]]:
    """Each rule's rejects that its pattern matches anyway; empty when all rules hold.

    The same shape the rollup measurement publishes as ``spot_check_failures``,
    so the tool and the test assert one thing.
    """
    failures: dict[str, list[str]] = {}
    for rule in CITATION_RULES:
        bad = [candidate for candidate in rule.rejects if rule.reads(candidate)]
        if bad:
            failures[rule.name] = bad
    return failures


__all__ = [
    "BILL_TYPES_BY_LENGTH",
    "CITATION_RULES",
    "CITATION_RULES_BY_NAME",
    "CITATION_RULE_SET_VERSION",
    "COMMITTEE_CHAMBERS",
    "COMMITTEE_ROUTES",
    "CONGRESS_CHAMBER",
    "DOCUMENT_CITATION_KINDS",
    "MONTHS",
    "NAMED_CHAMBER",
    "CitationContext",
    "CitationError",
    "CitationFinding",
    "CitationRule",
    "CommitteeResolution",
    "GrammarHit",
    "GrammarReader",
    "bill_type_and_number",
    "canonical_alnum",
    "committee_vocabulary",
    "find_citations",
    "named_chamber",
    "page_starts",
    "rejected_lookalikes",
    "resolve_committee_names",
]
