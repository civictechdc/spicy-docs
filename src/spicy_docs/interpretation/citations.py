"""What one document's text cites, as named rules over the normalized text.

Reads the parser-ready text of one document
(``extraction.body_text.rendition_text``'s ``BodyText``), its per-page split
where the rendition carries one, and -- for the committee rule alone -- the
chamber rosters this repository already reads, and returns one
:class:`CitationFinding` per occurrence naming the kind, the rule and its
version, the canonical target key in the hosted table's own spelling, the
exact text that matched, and the character offsets and printed page where it
was read. The patterns are measured, lifted unchanged from the rollup tool
that now imports them from this module so measurement and product cannot
drift, and each rule carries the lookalikes it must reject, asserted in
``tests/test_citations.py`` so a rule that widened into prose fails a check
rather than raising a hit rate. The committee resolver takes the roster
vocabulary as an argument, so this module stays pure: nothing fetches, reads a
file or a clock.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from spicy_docs.schemas.tables import natural_key


class CitationError(ValueError):
    """The text and the page split handed to a rule do not describe one document."""


# --- canonical forms -----------------------------------------------------------------


def canonical_alnum(value: str) -> str:
    """``H.R. 7806``, ``HR 7806`` and a wrapped ``H.R.\\n7806`` are one key."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def canonical_law_number(value: str) -> str:
    """``P.L. 98-369``, ``Public Law 98–369`` and the index's ``PUB 98-369`` are one key."""
    digits = re.search(r"(\d{1,3})[-–](\d{1,4})", value)
    return f"{digits.group(1)}-{digits.group(2)}" if digits else canonical_alnum(value)


def canonical_digits(value: str) -> str:
    """Every run of non-digits becomes one hyphen: ``12 Stat. 45`` is ``12-45``."""
    return re.sub(r"[^0-9]+", "-", value.strip())


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
#: re-derived from measured false positives (module docstring).
CONGRESS_CHAMBER = (
    r"(?<!U\.)(?<!U\.\s)(?<![A-Za-z])"
    r"(?:H\.?\s?R|H\.?\s?J\.?\s?Res|H\.?\s?Con\.?\s?Res|H\.?\s?Res"
    r"|S\.?\s?J\.?\s?Res|S\.?\s?Con\.?\s?Res|S\.?\s?Res|S)"
)


# --- the committee vocabulary and the resolver ---------------------------------------


def committee_vocabulary(*, house: Iterable[object] = (), senate: Iterable[object] = ()) -> tuple[tuple[str, str], ...]:
    """``(canonical name, system_code)`` for every committee the given rosters state.

    Takes what the readers in ``sources/congress/committee_rosters.py`` already
    produced -- ``HouseMemberData`` records for ``house``, ``SenateCvc``
    records for ``senate`` -- and reads them structurally, so this module stays
    pure. The Senate ``cvc`` file states only the committees its listed
    senators sit on, so that side is a floor and a name it does not reach stays
    unresolved rather than being guessed at.
    """
    entries: dict[str, str] = {}
    for roster in house:
        for committee in getattr(roster, "committees", ()):
            code = getattr(committee, "system_code", None) or "hs" + str(committee.code).lower()
            entries.setdefault(canonical_alnum(committee.name), code)
    for roster in senate:
        for senator in getattr(roster, "senators", ()):
            for assignment in getattr(senator, "committees", ()):
                entries.setdefault(canonical_alnum(assignment.name), assignment.system_code)
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
    writes ``H.R. 7806`` and never the Congress, so the caller supplies the one
    its own index record states, and a bill key is built only from a stated
    Congress -- with none, the finding keeps the printed form and says it is
    unresolved. ``committees`` is the ``{canonical candidate:
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

    **The Congress is an assumption, and a bounded one**: a print never states
    one, so every bare designator is stamped with the caller's, and an activity
    report that discusses an earlier Congress's law publishes a ``bill_id`` for
    the wrong Congress with ``target_resolved`` true -- which is why
    ``house_activity_reports`` carries ``bills_congress_mismatch``. Without a
    stated Congress the canonical printed form stands and the finding says the
    key is not the catalog's; the type/number split runs longest-name-first so
    ``S. Res. 21`` is ``sres`` and not ``s``.
    """
    parts = bill_type_and_number(value)
    if parts is None or context.congress is None:
        return canonical_alnum(value), False, "bill_number"
    return natural_key(context.congress, *parts), True, "bill_number"


def _public_law_target(value: str, _context: CitationContext) -> tuple[str, bool, str]:
    """``Pub. L. No. 118-31`` is ``118-public-31``: the ``laws`` identity, joined.

    Always ``public``, because this rule's pattern reads only the public
    spellings (a private law prints ``Private Law`` and is not matched), and
    the Congress comes from the cite itself.
    """
    number = canonical_law_number(value)
    congress, _, within = number.partition("-")
    if not congress.isdecimal() or not within.isdecimal():
        return number, False, "public_law"
    return natural_key(congress, "public", within), True, "public_law"


_USC_PARTS = re.compile(r"(\d{1,2})\s+U\.?\s?S\.?\s?C\.?\s+(?:§{1,2}\s?)?(\d[\w.–-]*)")
_CFR_PARTS = re.compile(r"(\d{1,2})\s+C\.?\s?F\.?\s?R\.?\s+(?:part\s+|§\s?)?(\d[\w.–-]*)")
_FEDERAL_REGISTER_PARTS = re.compile(r"(\d{1,3})\s+Fed\.?\s?Reg\.?\s+([\d,]{3,9})")
_DOCKET_PARTS = re.compile(r"(\d{2})[-–](\d{1,4})")
_US_REPORTS_PARTS = re.compile(r"(\d{1,3})\s+U\.\s?S\.\s+(\d{1,4})")
_RIN_NUMBER = re.compile(r"\d{4}[-–][A-Z]{2}\d{2}")


def _two_part_target(name: str, pattern: re.Pattern[str], *, strip: str = "") -> TargetReader:
    """``{first}-{second}`` from a two-part cite, or the printed form unresolved."""

    def read(value: str, _context: CitationContext) -> tuple[str, bool, str]:
        parts = pattern.search(value)
        if parts is None:
            return canonical_alnum(value), False, name
        second = parts.group(2)
        for character in strip:
            second = second.replace(character, "")
        return f"{parts.group(1)}-{second}", True, name

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


def _rin_target(value: str, _context: CitationContext) -> tuple[str, bool, str]:
    """``RIN: 3133-AF97`` is ``3133-AF97``, the spelling the Federal Register record uses.

    ``federal_register.regulation_id_numbers_json`` holds the bare number, so
    the label and the punctuation the print sets come off; the measurement's
    canonical form keeps them and is deliberately left alone.
    """
    match = _RIN_NUMBER.search(value)
    if match is None:
        return canonical_alnum(value), False, "rin"
    return match.group(0).replace("–", "-"), True, "rin"


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


@dataclass(frozen=True, slots=True)
class CitationRule:
    """One measured extraction rule, what it joins to, and what it must reject.

    ``pattern`` carries no capturing group, so one match is one string on every
    reader (a test holds it to that); a rule that needs the match's parts reads
    them in its own ``target`` with a second, local pattern, which keeps the
    measured pattern byte-identical to what was measured. ``index_pattern``
    exists because the two sides spell the same fact differently (Congress.gov
    states ``PUB 98-369`` where the print says ``P.L. 98-369``) and both sides
    reduce to ``canonical`` before any comparison, so a key the index already
    states is never counted as something only the document holds. ``version``
    moves when the pattern, the rejects or the target reader changes, and is a
    zero-padded decimal because a merge orders this column as a string.
    """

    name: str
    version: str
    pattern: str
    target_table: str
    target_key_shape: str
    rejects: tuple[str, ...] = ()
    note: str = ""
    #: How the *index* spells this key, when that differs from the print.
    index_pattern: str | None = None
    #: Both sides are reduced to this form before being compared.
    canonical: Callable[[str], str] = canonical_alnum
    #: The hosted key one match names.  Defaults to ``canonical``.
    target: TargetReader | None = None

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern)

    def compiled_index(self) -> re.Pattern[str]:
        return re.compile(self.index_pattern or self.pattern)

    def target_key(self, matched: str, context: CitationContext) -> tuple[str, bool, str]:
        reader = self.target or _target_from_canonical(self.name, self.canonical)
        return reader(matched, context)


CITATION_RULES: tuple[CitationRule, ...] = (
    CitationRule(
        name="bill_number",
        version="001",
        pattern=rf"{CONGRESS_CHAMBER}[.\s]\s?\d{{1,5}}\b",
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
        ),
        note="chamber designator plus number; the Congress must come from the document's own date or index row",
        target=_bill_target,
    ),
    CitationRule(
        name="public_law",
        version="001",
        # One rule for all four spellings in the sample: ``Public Law 98-369``,
        # ``P.L. 98-369``, ``PL 98-369`` and the Bluebook ``Pub. L. No. 89-136``.
        # The first rule could not read the Bluebook form and so missed 35
        # occurrences -- 18 in the activity reports, 11 in GAO -- which is the
        # shape a court or an auditor writes in.
        pattern=r"\bP(?:ub(?:lic)?)?\.?\s*L(?:aw)?\.?\s?(?:No\.\s?)?\d{1,3}[-–]\d{1,4}\b",
        index_pattern=(r"\b(?:P(?:ub(?:lic)?)?\.?\s*L(?:aw)?\.?\s?(?:No\.\s?)?|PUB\s+|PRIV\s+)\d{1,3}[-–]\d{1,4}\b"),
        canonical=canonical_law_number,
        target_table="laws",
        target_key_shape="(congress, law_type, number), joined: {congress}-public-{number}",
        rejects=("Public Lands", "P.L. Smith", "Pub L", "Republic Law 5", "Pub. L. Rev."),
        target=_public_law_target,
    ),
    CitationRule(
        name="statutes_at_large",
        version="001",
        pattern=r"\b\d{1,3}\s+Stat\.\s+\d{1,4}\b",
        canonical=canonical_digits,
        target_table="laws",
        target_key_shape="statutes_at_large_cite as {volume}-{page}",
        rejects=("Stat. of the Union", "12 State 45"),
    ),
    CitationRule(
        name="usc_section",
        version="001",
        pattern=r"\b\d{1,2}\s+U\.?\s?S\.?\s?C\.?\s+(?:§{1,2}\s?)?\d[\w.–-]*",
        target_table="law_code_sections",
        target_key_shape="{usc_title}-{usc_section}",
        rejects=("U.S. Code of conduct", "42 USC for"),
        target=_two_part_target("usc_section", _USC_PARTS),
    ),
    CitationRule(
        name="cfr_section",
        version="001",
        pattern=r"\b\d{1,2}\s+C\.?\s?F\.?\s?R\.?\s+(?:part\s+|§\s?)?\d[\w.–-]*",
        target_table="cfr sections (host-side)",
        target_key_shape="{title}-{part}",
        rejects=("CFR is the", "40 CRF 60"),
        target=_two_part_target("cfr_section", _CFR_PARTS),
    ),
    CitationRule(
        name="federal_register_cite",
        version="001",
        pattern=r"\b\d{1,3}\s+Fed\.?\s?Reg\.?\s+[\d,]{3,9}\b",
        target_table="federal_register",
        target_key_shape="{volume}-{start_page}; the host resolves document_number by that pair",
        rejects=("Fed. Reg. of the", "88 Federal agencies"),
        target=_two_part_target("federal_register_cite", _FEDERAL_REGISTER_PARTS, strip=","),
    ),
    CitationRule(
        name="rin",
        version="002",
        pattern=r"\bRIN[: ]\s?\d{4}[-–][A-Z]{2}\d{2}\b",
        target_table="federal_register",
        target_key_shape="the bare RIN, as regulation_id_numbers_json spells it",
        rejects=("RIN of the", "RIN 1234"),
        note=(
            "87 distinct RINs across the eight House activity reports and none in any CRPT MODS: "
            "the family's largest single citation yield, and invisible to a 60-page read"
        ),
        target=_rin_target,
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
        version="002",
        pattern=r"\b[A-Z]{2,7}[-–]\d{4}[-–]\d{4}\b",
        target_table="dockets",
        target_key_shape="docket_id as the agency prints it",
        rejects=("FAA 2016 6907", "ABC-16-0001"),
        note="38 distinct agency dockets across the eight House activity reports; no CRPT MODS states one",
        target=_printed_id_target("docket_number"),
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
        version="001",
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
    """A digest over every rule's name, version, pattern **and rejects**.

    Derived, not written: editing a pattern moves this even when someone
    forgets to move that rule's own ``version``, and the pinned test then names
    both. The rejects are in the input because they are part of the rule -- a
    reject that is no longer asserted cannot fail -- and so is the target
    reader's name, because swapping which function builds the published key
    changes that key without touching the pattern. It cannot see a change
    *inside* a reader; that is what the per-rule ``version`` is for.
    """
    joined = "\n".join(
        f"{rule.name}|{rule.version}|{rule.pattern}|{'|'.join(rule.rejects)}"
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
) -> tuple[CitationFinding, ...]:
    """Every cite the named rules find in one document's normalized text.

    ``pages`` is that same text's per-page split and is proved against ``text``
    rather than trusted, because a page map that does not rejoin would
    attribute every span to the wrong page silently; ``None`` means every
    finding's page is NULL, the honest answer rather than page 1. ``congress``
    is what a bare bill designator belongs to (see :class:`CitationContext`)
    and ``committees`` is the roster vocabulary from
    :func:`committee_vocabulary`. Findings come back in ``(kind, span)`` order,
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

    matches: dict[str, list[tuple[str, int, int]]] = {}
    for name in kinds:
        rule = CITATION_RULES_BY_NAME[name]
        matches[name] = [(m.group(0), m.start(), m.end()) for m in rule.compiled().finditer(text)]

    # A printed committee name is a candidate until a roster settles it, and it
    # is settled over the whole document at once: the sibling-prefix rule reads
    # the other candidates this document printed.
    candidates = sorted({canonical_alnum(value) for value, _, _ in matches.get("committee_name", ())})
    context = CitationContext(congress=congress, committees=resolve_committee_names(candidates, committees))

    findings: list[CitationFinding] = []
    for name in kinds:
        rule = CITATION_RULES_BY_NAME[name]
        for matched, start, end in matches[name]:
            target, resolved, route = rule.target_key(matched, context)
            findings.append(
                CitationFinding(
                    kind=rule.name,
                    rule_version=rule.version,
                    target_key=target,
                    target_table=rule.target_table,
                    target_resolved=resolved,
                    target_rule=route,
                    matched_text=matched,
                    span_start=start,
                    span_end=end,
                    page=None if not starts else bisect.bisect_right(starts, start),
                )
            )
    findings.sort(key=lambda finding: (finding.kind, finding.span_start))
    return tuple(findings)


def rejected_lookalikes() -> dict[str, list[str]]:
    """Each rule's rejects that its pattern matches anyway; empty when all rules hold.

    The same shape the rollup measurement publishes as ``spot_check_failures``,
    so the tool and the test assert one thing.
    """
    failures: dict[str, list[str]] = {}
    for rule in CITATION_RULES:
        compiled = rule.compiled()
        bad = [candidate for candidate in rule.rejects if compiled.search(candidate)]
        if bad:
            failures[rule.name] = bad
    return failures


__all__ = [
    "BILL_TYPES_BY_LENGTH",
    "CITATION_RULES",
    "CITATION_RULES_BY_NAME",
    "CITATION_RULE_SET_VERSION",
    "COMMITTEE_ROUTES",
    "CONGRESS_CHAMBER",
    "DOCUMENT_CITATION_KINDS",
    "MONTHS",
    "CitationContext",
    "CitationError",
    "CitationFinding",
    "CitationRule",
    "CommitteeResolution",
    "bill_type_and_number",
    "canonical_alnum",
    "canonical_digits",
    "canonical_law_number",
    "committee_vocabulary",
    "find_citations",
    "page_starts",
    "rejected_lookalikes",
    "resolve_committee_names",
]
