"""What one document's text cites, as named rules over the normalized text.

Publisher fact in: the parser-ready text of one document
(``extraction.body_text.rendition_text``'s ``BodyText``), its per-page split
where the rendition carries one, and -- for the committee rule alone -- the
chamber rosters this repository already reads.

Interpretation out: a :class:`CitationFinding` per occurrence, naming the kind,
the rule and its version, the canonical target key in the hosted table's own
spelling, the exact text that matched, and where it was read: character offsets
into that same normalized text, plus the printed page when the rendition states
page boundaries. A hosted row therefore carries its own audit trail beside the
value, the way ``press_releases`` carries its match and
``house_communications`` its RIN.

**These patterns are not new.** Every one was measured on 2026-09-20 over 71
documents in ten source families and is lifted here unchanged from
``tools/analysis/pdf_family_rollup.py``, which now imports them from this
module so the measurement and the product can never drift apart
(``docs/research/pdf-family-rollup-yield-2026-09-20.md``). Four of them were
wrong until that sample corrected them, and each correction is a comment beside
the pattern it explains:

* ``bill_number`` without its ``[.\\s]`` separator read the GPO running head
  ``HR974`` and the Congressional Record locator ``S4601`` as bills, and
  without its ``U.`` lookbehinds it read every U.S. Reports page cite
  (``600 U. S. 183``) as Senate bill ``S. 183``;
* ``public_law`` could not read the Bluebook ``Pub. L. No. 89-136``, the
  spelling a court or an auditor writes in, and so missed 35 occurrences;
* ``case_docket_number`` read the ``No. 89-136`` inside those same Bluebook
  cites as a circuit docket, and now refuses a ``No.`` preceded by ``L.``;
* ``committee_name`` is a *candidate* finder and not a committee: a committee
  report wraps the name across lines and runs it into the following prose, so
  90 distinct candidates over eight prints settled to 20 ``system_code``s.

Each rule carries the lookalikes it must reject, and
``tests/test_citations.py`` asserts the rejection, so a rule that widened into
prose shows up as a failing check rather than as a high hit rate.

**Purity.** Nothing here fetches, reads a file or a clock. The committee
resolver takes the vocabulary as an argument: :func:`committee_vocabulary`
builds it from whatever the chamber roster readers in
``sources/congress/committee_rosters.py`` already parsed, and the caller that
owns that acquisition passes it in.

**Complexity.** For text of ``C`` characters, ``K`` rules and ``V`` committee
candidates settled against ``R`` roster names, one pass per rule is
``O(K * C)``, page attribution is ``O(M log P)`` over ``M`` matches and ``P``
pages, and committee resolution is ``O(V * (R + V))`` with ``R`` a few dozen
and ``V`` about a hundred on the densest document measured. Nothing here is
superlinear in the corpus.
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
    pure and ``interpretation`` keeps its one-way dependency on ``sources``.

    The House file states the complete ``<committees>`` block; the Senate
    ``cvc`` file states only the committees its listed senators sit on, so the
    Senate side of any vocabulary built from it is a floor and a name it does
    not reach stays unresolved rather than being guessed at.  A House
    committee's ``system_code`` comes off its own accessor where the record has
    one, so the ``AG00 -> hsag00`` rule is stated once, in
    ``committee_rosters.house_system_code``.
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


def resolve_committee_names(values: Iterable[str], vocabulary: Sequence[tuple[str, str]]) -> dict[str, str | None]:
    """Settle each printed candidate against the rosters, or leave it unresolved.

    Four ways, in order, and each is a statement about the print rather than a
    guess: the candidate *is* a roster name; the candidate is a line-wrapped
    **prefix** of exactly one roster name (``Committee on Natural Re``); a
    roster name is a prefix of the candidate, which is the name running into
    following prose (``Committee on Ways and Means Repub``); or the candidate
    is a prefix of other candidates **in the same document** that all resolved
    to one committee, which is how ``Committee on Agri`` settles where the
    roster alone cannot -- it prefixes the House's Agriculture and the Senate's
    Agriculture, Nutrition, and Forestry, but the report that wrapped it also
    prints the full House name.

    A candidate that stays ambiguous, and every committee no supplied roster
    names, is reported unresolved rather than counted.

    ``O(V * (R + V))`` over one document's candidates and the roster, with R
    fixed at a few dozen and V at about a hundred.
    """
    resolved: dict[str, str | None] = {}
    for value in values:
        exact = [code for name, code in vocabulary if name == value]
        if exact:
            resolved[value] = exact[0]
            continue
        prefixed = {code for name, code in vocabulary if name.startswith(value)}
        if len(prefixed) == 1:
            resolved[value] = prefixed.pop()
            continue
        contains = sorted(
            ((name, code) for name, code in vocabulary if value.startswith(name)), key=lambda pair: -len(pair[0])
        )
        resolved[value] = contains[0][1] if contains else None
    for value, code in list(resolved.items()):
        if code is not None:
            continue
        siblings = {
            other_code for other, other_code in resolved.items() if other_code is not None and other.startswith(value)
        }
        if len(siblings) == 1:
            resolved[value] = siblings.pop()
    return resolved


# --- the rules -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationContext:
    """What a target key needs that the matched text alone does not state.

    ``congress`` is the Congress a bare bill designator belongs to.  A print
    writes ``H.R. 7806`` and never the Congress, so the caller supplies the one
    its own index record states -- the CRPT summary's ``congress`` for a
    committee report -- and a bill key is built only from a stated Congress,
    never from a guess.  With no Congress the finding keeps the printed form
    and says it is unresolved.

    ``committees`` is the ``{canonical candidate: system_code or None}`` map
    :func:`resolve_committee_names` produced for this one document.
    """

    congress: int | None = None
    committees: Mapping[str, str | None] = field(default_factory=dict)


#: ``(target key, whether the key is the hosted table's own spelling)``.
type TargetReader = Callable[[str, CitationContext], tuple[str, bool]]


def _target_from_canonical(canonical: Callable[[str], str]) -> TargetReader:
    return lambda value, _context: (canonical(value), True)


_BILL_SPLIT = re.compile(r"([A-Z]+)(\d{1,5})$")


def _bill_target(value: str, context: CitationContext) -> tuple[str, bool]:
    """``H.R. 7806`` in a 118th-Congress document is ``118-hr-7806``.

    The Congress is the caller's, from its own index record; without one the
    canonical printed form stands and the finding says the key is not the
    catalog's.  The type/number split runs longest-name-first so ``S. Res. 21``
    is ``sres`` and not ``s``.
    """
    canonical = canonical_alnum(value)
    split = _BILL_SPLIT.fullmatch(canonical)
    if split is None or context.congress is None:
        return canonical, False
    letters, number = split.group(1).lower(), split.group(2)
    kind = next((name for name in BILL_TYPES_BY_LENGTH if letters == name), None)
    if kind is None:
        return canonical, False
    return natural_key(context.congress, kind, number), True


def _public_law_target(value: str, _context: CitationContext) -> tuple[str, bool]:
    """``Pub. L. No. 118-31`` is ``118-public-31``: the ``laws`` identity, joined.

    Always ``public``: this rule's pattern reads only the public spellings, and
    a private law prints ``Private Law``, which it does not match.  The
    Congress comes from the cite itself, so no caller input is needed.
    """
    number = canonical_law_number(value)
    congress, _, within = number.partition("-")
    if not congress.isdecimal() or not within.isdecimal():
        return number, False
    return natural_key(congress, "public", within), True


_USC_PARTS = re.compile(r"(\d{1,2})\s+U\.?\s?S\.?\s?C\.?\s+(?:§{1,2}\s?)?(\d[\w.–-]*)")
_CFR_PARTS = re.compile(r"(\d{1,2})\s+C\.?\s?F\.?\s?R\.?\s+(?:part\s+|§\s?)?(\d[\w.–-]*)")
_FEDERAL_REGISTER_PARTS = re.compile(r"(\d{1,3})\s+Fed\.?\s?Reg\.?\s+([\d,]{3,9})")
_DOCKET_PARTS = re.compile(r"(\d{2})[-–](\d{1,4})")


def _two_part_target(pattern: re.Pattern[str], *, strip: str = "") -> TargetReader:
    """``{first}-{second}`` from a two-part cite, or the printed form unresolved."""

    def read(value: str, _context: CitationContext) -> tuple[str, bool]:
        parts = pattern.search(value)
        if parts is None:
            return canonical_alnum(value), False
        second = parts.group(2)
        for character in strip:
            second = second.replace(character, "")
        return f"{parts.group(1)}-{second}", True

    return read


def _gao_product_target(value: str, _context: CitationContext) -> tuple[str, bool]:
    """``GAO–24–106221`` is the product id ``gao/files.py`` selects on, ``GAO-24-106221``.

    The canonical form the measurement compares on strips the hyphens; the
    publisher's own id keeps them, so the stored key restores the spelling the
    selection key uses and the en-dash a print sets becomes a hyphen.
    """
    return value.strip().upper().replace("–", "-"), True


def _committee_target(value: str, context: CitationContext) -> tuple[str, bool]:
    """The ``system_code`` a roster settled this candidate to, or the candidate itself.

    An unresolved candidate is still stored, keyed on its own canonical printed
    form: it is evidence only the print holds, and dropping it would lose the
    committee this repository's pinned rosters happen not to reach.  The row
    says which it is, so a consumer joining ``committees.system_code`` can
    filter on one column instead of guessing from the key's shape.
    """
    canonical = canonical_alnum(value)
    code = context.committees.get(canonical)
    return (code, True) if code is not None else (canonical, False)


@dataclass(frozen=True, slots=True)
class CitationRule:
    """One measured extraction rule, what it joins to, and what it must reject.

    ``pattern`` carries no capturing group, so one match is one string on every
    reader (a test holds it to that); a rule that needs the match's parts reads
    them in its own ``target`` with a second, local pattern, which keeps the
    measured pattern byte-identical to what was measured.

    ``index_pattern`` exists because the two sides spell the same fact
    differently: Congress.gov states a related law as ``PUB 98-369`` while the
    print says ``P.L. 98-369``.  Both sides reduce to ``canonical`` before any
    comparison, so a key the index already states is never counted as something
    only the document holds -- the owner's first rule, made checkable.

    ``version`` moves when the pattern, the rejects or the target reader
    changes, and the fixtures' pinned counts move with it
    (``docs/decisions.md``).  It is a zero-padded decimal because a merge
    orders this column as a string.
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

    def target_key(self, matched: str, context: CitationContext) -> tuple[str, bool]:
        reader = self.target or _target_from_canonical(self.canonical)
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
        target=_two_part_target(_USC_PARTS),
    ),
    CitationRule(
        name="cfr_section",
        version="001",
        pattern=r"\b\d{1,2}\s+C\.?\s?F\.?\s?R\.?\s+(?:part\s+|§\s?)?\d[\w.–-]*",
        target_table="cfr sections (host-side)",
        target_key_shape="{title}-{part}",
        rejects=("CFR is the", "40 CRF 60"),
        target=_two_part_target(_CFR_PARTS),
    ),
    CitationRule(
        name="federal_register_cite",
        version="001",
        pattern=r"\b\d{1,3}\s+Fed\.?\s?Reg\.?\s+[\d,]{3,9}\b",
        target_table="federal_register",
        target_key_shape="{volume}-{start_page}; the host resolves document_number by that pair",
        rejects=("Fed. Reg. of the", "88 Federal agencies"),
        target=_two_part_target(_FEDERAL_REGISTER_PARTS, strip=","),
    ),
    CitationRule(
        name="rin",
        version="001",
        pattern=r"\bRIN[: ]\s?\d{4}[-–][A-Z]{2}\d{2}\b",
        target_table="federal_register",
        target_key_shape="the RIN, as regulation_id_numbers_json spells it",
        rejects=("RIN of the", "RIN 1234"),
    ),
    CitationRule(
        name="gao_product_id",
        version="001",
        pattern=r"\bGAO[-–]\d{2}[-–]\d{3,6}(?:[A-Z]{1,3})?\b",
        target_table="gao products (not hosted; gao/files.py selection key)",
        target_key_shape="product_id as GAO-YY-NNNNN",
        rejects=("GAO reported", "GAO-2026"),
        target=_gao_product_target,
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
        version="001",
        pattern=r"\b[A-Z]{2,7}[-–]\d{4}[-–]\d{4}\b",
        target_table="dockets",
        target_key_shape="docket_id as the agency prints it",
        rejects=("FAA 2016 6907", "ABC-16-0001"),
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
        target=_two_part_target(_DOCKET_PARTS),
    ),
    CitationRule(
        name="us_reports_cite",
        version="001",
        pattern=r"\b\d{1,3}\s+U\.\s?S\.\s+\d{1,4}\b",
        target_table="courtlistener opinions (not hosted)",
        target_key_shape="citation as {volume}-{page}",
        rejects=("U.S. Government", "600 US 1"),
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
#: table or publisher addresses.  ``bioguide_id`` is excluded because it
#: measured zero everywhere and no print states one; ``dollar_amount`` and
#: ``fiscal_year`` because they are quantities, not links, and have no target.
#: ``statutes_at_large``, ``rin``, ``docket_number`` and ``us_reports_cite``
#: stay in the rule set -- the measurement runs all sixteen -- and join the
#: stored kinds when a family that carries them is built (build order steps 2
#: and 3).
DOCUMENT_CITATION_KINDS: tuple[str, ...] = (
    "bill_number",
    "public_law",
    "usc_section",
    "cfr_section",
    "federal_register_cite",
    "gao_product_id",
    "crs_report_id",
    "case_docket_number",
    "committee_name",
)


def _rule_set_version(rules: Sequence[CitationRule]) -> str:
    """A digest over every rule's name, version and pattern.

    Derived, not written: editing a pattern moves this even when someone
    forgets to move that rule's own ``version``, and the pinned test then names
    both.  Twelve hex characters is 48 bits over a sixteen-row input.
    """
    joined = "\n".join(f"{rule.name}|{rule.version}|{rule.pattern}" for rule in rules)
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
    publisher's bytes -- so a consumer holding that text can re-read the span
    and see what the rule saw.  ``page`` is the printed page the match *starts*
    on, and is ``None`` for a rendition that states no page boundary; a match
    that straddles a boundary is attributed to the page it began on.
    """

    kind: str
    rule_version: str
    target_key: str
    target_table: str
    target_resolved: bool
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

    ``pages`` is that same text's per-page split -- ``BodyText.pages`` -- and
    is proved against ``text`` rather than trusted: a page map that does not
    rejoin to the text would attribute every span to the wrong page, silently.
    Pass ``None`` for a rendition that states no page boundary and every
    finding's ``page`` is NULL, which is the honest answer rather than page 1.

    ``congress`` is what a bare bill designator belongs to (see
    :class:`CitationContext`), and ``committees`` is the roster vocabulary from
    :func:`committee_vocabulary`.  Findings come back in ``(kind, span)``
    order, which is stable and independent of the rules' own order.
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
            target, resolved = rule.target_key(matched, context)
            findings.append(
                CitationFinding(
                    kind=rule.name,
                    rule_version=rule.version,
                    target_key=target,
                    target_table=rule.target_table,
                    target_resolved=resolved,
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
    "CONGRESS_CHAMBER",
    "DOCUMENT_CITATION_KINDS",
    "MONTHS",
    "CitationContext",
    "CitationError",
    "CitationFinding",
    "CitationRule",
    "canonical_alnum",
    "canonical_digits",
    "canonical_law_number",
    "committee_vocabulary",
    "find_citations",
    "page_starts",
    "rejected_lookalikes",
    "resolve_committee_names",
]
