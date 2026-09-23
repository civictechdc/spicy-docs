"""One home for CFR and legal-authority citation grammars.

Five implementations of this existed across the repositories: SpicySearch's
``identifiers.py`` (the origin), a port of it into ``spicy_regs/ontology/
citations.py`` (the most evolved — 24 compiled patterns, several bought with
evidence files), that repository's ``build_authority_edges`` consumer, a
filtering consumer's keep-logic, and an earlier version of this module written
without reading the other four. This version is the deliberate union: every
rule below that cites a source was carried over because it was *bought* —
with a bakeoff false positive, a benchmark miss, or a mis-minted URN — and
none of them was ours to rediscover.

**What this module refuses to do.** Nothing is repaired and nothing is
dropped. A citation whose title cannot exist is returned with a false verdict;
an authority string nothing here can read comes back as ``other``/``failed``
rather than vanishing. The consumer filtering for real citations and the
consumer studying publisher damage need the same rows.

Provenance of the load-bearing rules:

- Boundary guards (``_LEFT``/``_RIGHT``): SpicySearch — without them
  "040 CFR 060" matched at offset 1 and reported a fabricated "40 CFR 60".
- Dash normalization: SpicySearch/USLM readers — seven Unicode dash
  codepoints collapse to "-", one character for one character, so spans on
  the normalized text still index the original.
- Trailing-punctuation rule in the section capture: SpicySearch — a greedy
  capture read "49 CFR 900.42." as section "900.42." and the whole citation
  was then dropped rather than the period.
- The Title 3 compilation diversion: citations.py — "3 CFR, 1977 Comp.,
  p. 123" locates an Executive Order's printed page; there is no 3 CFR
  § 1977, and a CFR grammar that reads one fabricates a citation. The
  closed separator set inside it was bought when an enumerated set left
  "through" still minting ``urn:rkaf:us:cfr:3:1949``.
- The U.S.C. range ordering rule: citations.py — a hyphen means two things
  in the U.S. Code ("1395w-4" is one section's name; "7401-7671q" is a
  range), nothing in the characters distinguishes them, and the ordering
  does. Fail-closed where nothing decides: "4801-4582" and "80a-06" stay one
  opaque token because reading them either way would be an invention. The
  ABBREVIATED span "1484-86" was in that company until 2026-08-22, when a
  section-existence oracle settled it — see :func:`_abbreviated_span`, where
  the oracle is what buys the reading and six real sections it cannot fence
  are named.
- The chapter grammar: citations.py — bought as the largest well-defined
  slice of the citation bakeoff's shared-miss cell (31 strings neither
  implementation detected).
- Capitalization as evidence: SpicySearch — bare "EO" must be uppercase and
  "Stat" capitalized, or prose mints citations ("Romeo" contains "eo").
- Zero-padded titles read by integer value: this module — the Unified
  Agenda's structured field zero-pads 95 titles ("07 CFR 1943" is USDA's
  title 7), and a [1-9] capture silently dropped all of them.
- Lettered CFR parts: this module — the OFR's own index lists 272 parts
  with a letter suffix among its 8,424, and "7 CFR 15" and "7 CFR 15a" are
  separate parts; every ancestor merged them.
- Right-hand boundaries on internal tokens (2026-08-22): the ``_LEFT`` and
  ``_RIGHT`` guards above fence a whole citation, and nothing fenced the
  tokens INSIDE one. Two defects came out of that single omission — a
  section marker that began ordinary words ("Social Security" offered "Sec"
  and gave up "urity"), and a section suffix that ate the next word's
  letters ("6921through" became section "6921thr"). Both are fixed by giving
  the token its own right edge, and the shape is worth remembering: a
  citation's outer boundary says nothing about its inner ones.

**Where the rules live.** A rule is written once and named. Six patterns
spelled the U.S.C. section token out identically before this, three spelled
the section marker, eleven spelled the damaged code label, and twenty
families each restated "a match is a row, statused by its span" by hand.
What looks like duplication and is NOT has a comment saying so at the site —
the two treaty volume bounds, the anchored and windowed list walks, the
appendix span fence — because merging two rules that only resemble each
other is worse than the restatement was.

**Provenance.** Moved into spicy-docs on 2026-09-23 as the stack's canonical
data-side citation grammar (consolidation item B4 in
``docs/research/consolidation-path-2026-09-22.md``; the five-grammar bakeoff
that chose it is ``docs/research/parsing-survey-2026-09-23.md`` section 5). The
source is RefSpec ``src/refspec/registry/citation_grammar.py`` at RefSpec
``4a680c81``, unchanged since ``c9cc5410`` and so byte-identical to what the
survey measured at ``f83c0d7a``, and every RefSpec test that exercises it
passed against this copy when it landed. This is the canonical copy now, and
it has changed since: it is linear in its text, it locates Public Law,
Statutes and Federal Register citations in running text, it reads four shapes
it dropped, and it folds a U.S. Code section through the tables' own
``usc_section_key`` (its one import beyond the standard library). The list,
with the two RefSpec expectations that move, is ``docs/decisions.md``, "The
stack's citation grammar and identifier shapes live here". The self-contained tests are ported to
``tests/test_citation_grammar.py``; the ones that read RefSpec's pinned inputs
stay beside those inputs and run here once RefSpec imports this module back.
``refspec.registry.*`` names below are RefSpec modules that stay in RefSpec.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass, replace
from itertools import accumulate
from string import ascii_lowercase
from typing import Any

from spicy_docs.schemas.tables import DASH_SPELLINGS, usc_section_key

# Every name a consumer outside this module reads. Six of these were reached
# by siblings and tests while absent from the list -- ``states_nothing`` and
# the two stated-fact readers among them -- so the list named a smaller module
# than the one that exists.
__all__ = [
    "CFR_LETTERED_PART_SHARE",
    "CFR_TITLE_COUNT",
    "CITATION_STRUCTURE_WORDS",
    "CONGRESS_CURRENT",
    "EO_HIGHEST_KNOWN",
    "FR_LABEL_MAX_EDITS",
    "FR_PAGE_HIGHEST_KNOWN",
    "FR_VOLUME_HIGHEST_KNOWN",
    "PL_FIRST_NUMBERED_CONGRESS",
    "STAT_VOLUME_HIGHEST_KNOWN",
    "UNSTATED_SENTINELS",
    "USC_RESERVED_TITLES",
    "USC_SPAN_ABBREVIATED",
    "USC_SPAN_STATED",
    "USC_TITLE_COUNT",
    "ActRelativeCitation",
    "ActRelativeCitationOccurrence",
    "AuthorityCitation",
    "AuthorityCitationOccurrence",
    "CfrCitation",
    "CfrCitationOccurrence",
    "CfrCitationRange",
    "EoCompilationLocator",
    "EoCompilationOccurrence",
    "FederalRegisterCitation",
    "FederalRegisterCitationOccurrence",
    "LocalClauseOccurrence",
    "SupremeCourtCitation",
    "TimetableFrCitation",
    "UscCitationOccurrence",
    "act_name_with_trailing_year",
    "damerau_levenshtein",
    "find_act_relative_citations",
    "find_act_relative_occurrences",
    "find_cfr_citations",
    "find_eo_compilation_locators",
    "find_federal_register_citations",
    "find_local_clause_occurrences",
    "find_public_law_citations",
    "find_statute_citations",
    "find_usc_citations",
    "names_citation_structure",
    "normalize_popular_name",
    "parse_agenda_timetable_citation",
    "parse_authority_citation",
    "parse_cfr_citations",
    "parse_eo_compilation_locators",
    "parse_federal_register_citations",
    "parse_supreme_court_citation",
    "stated_act_name",
    "stated_section",
    "states_nothing",
    "statutes_volume_matches_congress",
    "usc_section_ceilings",
    "usc_section_magnitude_is_plausible",
    "usc_section_pinpoint",
    "usc_title_is_possible",
    "usc_token_is_chapter_qualified",
]

#: The Code of Federal Regulations has 50 titles. Title 35 is Reserved TODAY
#: but was the Panama Canal title through the 2000 revision — the Canal Zone
#: was U.S.-controlled until the 1999 handover — so a citation to 35 CFR in a
#: 1990s document is real. The grammar judges citations, which have dates;
#: the subject-index module keeps its own present-day reserved set for
#: judging today's roster.
CFR_TITLE_COUNT = 50

#: The U.S. Code has 54 titles. Title 53 is reserved and — unlike CFR title
#: 35, which held the Panama Canal until 2000 — has NEVER held content, so a
#: citation to it is impossible in any year. Title 54 (National Park Service)
#: was enacted 2014-12-19.
USC_TITLE_COUNT = 54
USC_RESERVED_TITLES = frozenset({53})

#: Series bounds for damage detection, each a verified fact with a date. A
#: value beyond its series is damage IN DATA CAPTURED BEFORE the as-of date;
#: these are for builders judging pinned captures, not for the grammar to
#: hard-refuse (the next Congress will outrun them, the way the CFR's 2025
#: roster outran 1990s Panama citations).
EO_HIGHEST_KNOWN = 14_420  # as of 2026-08; the numbered series starts at 1
#: Volume 140 carries the 2026 session laws: Pub. L. 119-101 (21st Century
#: ROAD to Housing Act, approved 2026-07-11) runs 140 Stat. 846-984, and the
#: session's laws run 140 Stat. 3 through 140 Stat. 985 so far. Moved from 139
#: on 2026-08-22 with no row in the pinned capture citing it — which is the
#: point: a bound is cheapest to widen BEFORE the edition that would trip it.
STAT_VOLUME_HIGHEST_KNOWN = 140
PL_FIRST_NUMBERED_CONGRESS = 57  # numbered Public Laws begin in 1901
CONGRESS_CURRENT = 119  # as of 2026-08
FR_VOLUME_HIGHEST_KNOWN = 91  # volume 1 = 1936, so volume 91 = 2026
FR_PAGE_HIGHEST_KNOWN = 100_000  # the Register's widest year is under 100k pages


def usc_title_is_possible(title: int | None) -> bool | None:
    """1-54, excluding never-enacted 53. None when there is no title to judge."""

    if title is None:
        return None
    return 1 <= title <= USC_TITLE_COUNT and title not in USC_RESERVED_TITLES


#: The Congress from which the Statutes at Large print TWO volumes per
#: Congress rather than one. Before it the series ran one volume per Congress
#: and ``volume = congress - 25``; from it the series is annual and
#: ``volume ∈ {2C-99, 2C-98}``. Derived, not assumed: over the pinned OLRC
#: index in ``research/evidence/silent-misreads-2026-08-22/
#: pl-congress-to-statutes-volume.csv`` the relation holds for every one of
#: the 63 congresses with coverage that has issued numbered Public Laws
#: (57th-119th), and the minimum volume equals 2C-99 for all 35 of the
#: 85th-119th.
_STATUTES_ANNUAL_FROM_CONGRESS = 74


def statutes_volume_matches_congress(congress: int | None, volume: int | None) -> bool | None:
    """Whether a Statutes volume can carry a law of that Congress.

    A FENCE, one volume wider on each side than the relation it is derived
    from, because two congresses in the pinned index reach a third volume: the
    75th runs {50, 51, 52} where the relation says {51, 52}, and the 93rd runs
    {87, 88, 89} where it says {87, 88}. Deriving tight and fencing loose is
    what keeps a bound from calling real citations damage the first time the
    publisher does something the derivation had not seen.

    The widening now has ZERO REMAINING MARGIN, and it is worth knowing before
    the next one: the 75th spends the lower volume (50 = 2C-100) and the 93rd
    spends the upper (89 = 2C-97), so a congress reaching a FOURTH volume would
    be called damage by this fence rather than absorbed by it.

    None where there is nothing to judge — no volume, or a Congress outside
    the numbered Public Law series, which ``pl_congress_in_series`` already
    reports loudly and which the relation says nothing about.
    """

    if congress is None or volume is None:
        return None
    if not PL_FIRST_NUMBERED_CONGRESS <= congress <= CONGRESS_CURRENT:
        return None
    if congress < _STATUTES_ANNUAL_FROM_CONGRESS:
        return congress - 26 <= volume <= congress - 24
    return 2 * congress - 100 <= volume <= 2 * congress - 97


#: 272 of the 8,424 parts in the OFR's published subject index carry a letter
#: suffix. Recorded so the part capture below is not "simplified" back to
#: digits by someone who has not counted.
CFR_LETTERED_PART_SHARE = (272, 8_424)

#: Real CFR parts reach FIVE digits — 5 CFR 10001 and 10002 (National Council
#: on Disability) exist today — so five digits proves nothing either way:
#: "40 CFR 60758" is still fused-dot damage, but a length rule cannot tell it
#: from 10001. Only six digits and up is asserted implausible ("42 CFR
#: 412106"). The evidence-grade signal for five-digit parts is membership in
#: the OFR's own part index, which the Agenda tables carry as a column.
_MAX_PLAUSIBLE_PART_DIGITS = 5

# Boundary guards: no citation may start or end inside a longer token.
#
# A hyphenated NUMBER is a longer token too, and the first guard alone could
# not say so: a hyphen is neither a digit nor a letter, so a match was free to
# begin at the second half of "109-162". The Statutes reader did exactly that
# and published volume 162 out of a Public Law number's tail (6 distinct
# values, 9 source rows, measured 2026-08-22 -- every one a phantom, and no
# real citation in the corpus begins immediately after a digit-hyphen). This
# is the same defect class the module already fixed for the Register in
# :data:`_ANOTHER_CITATION_AHEAD`, at the one separator that rule cannot see.
#
# The two lookbehinds stay separate expressions because they say different
# things: one fences a WORD, the other a hyphenated NUMBER. Merging them into
# a character class would also refuse a citation after a bare leading dash,
# which nothing here has evidence against.
_LEFT = r"(?<![0-9A-Za-z])(?<!\d-)"
_RIGHT = r"(?![0-9A-Za-z])"


def _guarded(body: str) -> str:
    """``body`` with the boundary guards on both ends.

    Written once because a guard is easy to forget on one side of one pattern
    and the omission is silent: the pattern keeps matching, just also at
    offsets inside longer tokens.
    """

    return f"{_LEFT}{body}{_RIGHT}"


#: What follows a list separator when the next thing is ANOTHER CITATION
#: rather than another list member. "17 CFR 240, 15 U.S.C. 78c" lists no part
#: 15, and "5 U.S.C. 301, 117 Stat. 429" lists no section 117 — one rule, and
#: the CFR and U.S.C. list grammars both spell it here so they cannot drift.
#:
#: The Federal Register was missing from the family list even though this
#: module has read FR citations since the timetable builder needed them, and
#: the omission harvested phantom sections out of FR VOLUME numbers: "5
#: U.S.C. 301, as well as Secretary of Labor's Order 03-2006, 71 FR 4219"
#: published a section 71 of title 5. That is not a judgement that 5 U.S.C.
#: 71 is impossible — though it is: former § 71 was folded into § 5536 by
#: Pub. L. 89-554 in 1966 and never reused (OLRC's disposition table for
#: former title 5). It is self-consistency. The module's own FR grammar
#: reads "71 FR 4219" as volume 71, page 4219 of the 2006 Register, and
#: emits that row from the same string; a number cannot be a Register volume
#: and a Code section at once.
#:
#: The same argument reaches four more families, and they were missing for the
#: same reason the Register was: this module READS them out of the same string.
#: A treaty series locates an instrument by volume and page ("19 U.S.T. 6223",
#: "1870 U.N.T.S. 167") and a case reporter locates a decision the same way
#: ("340 U.S. 462", "141 F.3d 662", "142 S. Ct. 1987"), so a number leading one
#: of those is a VOLUME and cannot also be a Code section. Measured 2026-08-24
#: over all 42,677 authority values and all 8,240 notes: 18 occurrences in the
#: values and 14 in 10 notes, every single one a case name or a treaty title
#: with a U.S.C. citation somewhere in front of it — "United States ex rel.
#: Touhy v. Ragen, 340 U.S. 462 (1951)" behind "50 U.S.C. 403g" published 50
#: U.S.C. 340, and "Protocol Relating to the Status of Refugees, November 1,
#: 1968, 19 U.S.T. 6223" behind "8 U.S.C. 1101" published 8 U.S.C. 19. Every
#: one of them keeps a typed row: the treaty and reporter families read the
#: citation the number really belongs to, out of the same value.
_ANOTHER_CITATION_AHEAD = (
    r"(?!\s*(?:U\.?\s*S\.?\s*C|C\.?\s*F\.?\s*R|Stat\b|FR\b|Fed\.?\s?Reg"
    r"|U\.?\s?S\.?\s?T\b|U\.?\s?N\.?\s?T\.?\s?S\b|T\.?\s?I\.?\s?A\.?\s?S\b"
    r"|U\.\s?S\.\s*\d|S\.\s?Ct\b|F\.?\s?(?:2d|3d|4th)\b|F\.?\s?Supp\b|Cl\.?\s?Ct\b))"
)

#: The truncation signature itself, spelled ONCE: a dot, a digit run, and no
#: CFR marker leading away from them. Two readers need it in two forms — as
#: the negative lookahead :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` that
#: fences a section slot INSIDE a pattern, and as the positive
#: :data:`_DOT_TRUNCATES_A_SECTION` that
#: ``_usc_leading_section_is_untruncated`` applies to a match already made —
#: and they were written out twice, 2,000 lines apart. Measured drift hazard,
#: not a hypothetical one: with the carve-out deleted from either copy alone,
#: the Privacy Act specimen below still parses, because the OTHER copy still
#: carries it — so neither copy's own test can see its guard go missing.
#:
#: The CFR marker here is matched case-sensitively where this signature is
#: compiled alone (:data:`_DOT_TRUNCATES_A_SECTION`) and case-insensitively
#: where the pattern embedding the lookahead carries ``re.IGNORECASE``. The
#: difference is left standing rather than closed, because closing it would
#: widen a carve-out no source asks for: measured 2026-09-01 over all 42,677
#: distinct authority values and all 8,240 notes, exactly ONE text puts a
#: dot-digit run in front of a CFR marker at all — the uppercase Privacy Act
#: specimen named below — and a case-INSENSITIVE scan of the same corpus
#: finds no second one.
_DOT_TRUNCATION_SIGNATURE = rf"\.(?>\d+)(?!\s*C\.?\s*F\.?\s*R\.?{_RIGHT})"

#: The sibling of :data:`_ANOTHER_CITATION_AHEAD`, at the separator that rule
#: cannot see: what follows a number when the number is the PART OF A CFR
#: SECTION rather than a U.S.C. section of its own. A dot and more digits is the CFR's own compound
#: spelling ("155.490" is part 155, section 490) and the U.S. Code has no such
#: shape — a Code section's inner punctuation is a hyphen, never a dot. No
#: real U.S.C. identity contains one: checked against all 66,780 enumerated
#: title/section pairs the section-existence oracle carries.
#:
#: CORRECTED 2026-09-01: this fence shipped scoped to the LIST TAIL alone, on
#: the stated assumption that a dotted number reached ANCHORED to a code name
#: stays visibly "partial" and so does no silent harm. Measured false. "26
#: USC 1.104-1(c)" — an income-tax REGULATION, 26 CFR 1.104-1 — anchors
#: :data:`_USC_STANDARD` at "1", leaves ".104-1(c)" as an uncovered tail, and
#: the row does read ``parse_status`` "partial" exactly as predicted — but
#: "partial" is not visible to a consumer that reads ``usc_title``/
#: ``usc_section`` and the section-existence oracle without also checking
#: ``parse_status``, and every consumer measured does exactly that (the
#: builder's own by-status verdict census keys on ``parse_status`` but still
#: computes and reports a verdict for "partial" rows; the inv-universe
#: review's own crosstab script selected on ``authority_type`` alone). 26
#: U.S.C. 1 exists — it is the income tax rate schedule, and has nothing to
#: do with the regulation — so the row reads an affirmative, wrong "exists".
#: 41 distinct authority values / 175 rows / 36 RINs measured this way
#: (research/evidence/reg-dot-fence-2026-09-01/), 89 of them an affirmative
#: wrong "exists" — a full old-vs-new replay of THIS module over every
#: distinct authority value, which is the basis that directory's DELTAS.md
#: and this module's tests both use. The mined ledger's own 155 rows / 31
#: RINs / 90 came from a hand-written regex matching only the anchored
#: "title USC part.section" spelling: it missed the appendix and
#: transposed-label positions this fence also covers, and counted rows the
#: replay does not. The fix widens the SAME refusal to every position that
#: reads a single, bare section token as a complete citation on its own —
#: the anchor (:data:`_USC_STANDARD`), the appendix and transposed-label
#: forms, and the Internal Revenue Code self-name — so the citation is
#: refused outright
#: (``other``/``failed``, or read by nothing at this position) rather than
#: minted on a truncated read. A RANGE END is deliberately NOT one of these
#: positions; see below.
#:
#: The refusal carries one measured exception, found by reading the raw
#: record rather than trusting the count: "5 USC 552a.45 CFR s 5b.11(b)
#: (2)(ii)(H)" (RIN 0938-AO69, REGINFO_RIN_DATA_200610.xml line 82048) is
#: NOT a truncated regulation number. "552a" is the Privacy Act, a complete,
#: real, standalone U.S.C. section on its own (5 U.S.C. § 552a) — 552a is a
#: real repeated-letter section token where the digits before the letter are
#: not a truncated prefix. The dot is a missing separator, not a fused
#: number: the filer ran a second citation, 45 CFR 5b.11(b)(2)(ii)(H) —
#: corroborated by this RIN's own ``CFR_LIST``, "45 CFR 5b" — directly
#: against the first with no space or semicolon between them. Refusing here
#: would have deleted a real section for one that is not confused with
#: anything. This is the ONLY value anywhere in the corpus (all 42,677
#: distinct authority values) where a dotted number is immediately followed
#: by an explicit CFR citation, so the guard names the exception rather than
#: widening past it: the refusal does not fire when the digits after the dot
#: lead straight into "CFR".
#:
#: It guards a SINGLE section token and not a hyphenated span, and that is a
#: measured line rather than a cautious one, unchanged by the widening above:
#: guarding the span too would refuse a RANGE rather than truncate it, which
#: is worse. Every dotted list-tail item in the corpus was read: 187 in the
#: 42,677 authority values and 1,140 in the 8,240 notes, and every single one
#: is a bare number before the dot — a CFR part ("7 CFR 2.22, 2.80, and
#: 371.4"), a delegation ("49 CFR 1.81 and 1.95"), a Farm Credit Act section
#: ("Secs. 5.9, 5.10, 5.17"), an IRS regulation ("Sections 1.1362-1, ... and
#: 1.1363-1"). Exactly ONE instance anywhere puts a hyphenated span before
#: the dot, and it is not a compound at all: 12 CFR 326's note ends "31
#: U.S.C. 5311-5314, 5316-5332.2", where the "2" is a FOOTNOTE MARKER the
#: publisher prints superscript and this cache flattens — the same part's own
#: heading flattens the same footnote, "PART 326—MINIMUM SECURITY DEVICES AND
#: PROCEDURES AND BANK SECRECY ACT 1 COMPLIANCE". Guarding the span too would
#: have deleted the Bank Secrecy Act's own range from the note that grants
#: it, and taken two rows of 31 U.S.C. 5318 (RIN 3064-AC19) from "present" to
#: "near-miss" on the strength of a footnote. The SAME range, spelled with
#: "to" instead of a dash and standing alone rather than in a list ("31 USC
#: 5316 to 5332.2"), reaches :data:`_USC_STANDARD`'s own range tail — also
#: unguarded, for the identical reason: 2 further rows, measured in the same
#: pass that widened the anchor above.
_A_DOTTED_NUMBER_IS_A_CFR_SECTION = rf"(?!{_DOT_TRUNCATION_SIGNATURE})"

#: A section marker, everywhere one is written. Accreted in three spellings
#: that differed only in whether "section." kept its period; one expression
#: now, because "the word that introduces a section number" is one rule.
#:
#: The spelling merged TO is the wider of the three — it admits "Section." —
#: because merging to the narrower one would have narrowed two readers, and a
#: narrowing needs evidence that the refused form cannot be real. Here the
#: evidence runs the other way: modern practice abbreviates ("Sec.") or uses
#: the sign (GPO Style Manual ch. 9; Bluebook), so "Section." is not a
#: current citation marker — but the engrossed Constitution writes exactly
#: "Section. 1." in Article I, and this module reads the Constitution. The
#: merge is safe regardless of that argument: this marker never stands alone.
#: Every pattern using it anchors on a code, part or title first, so a
#: sentence-final "section." cannot donate one. Measured inert over all
#: 42,642 distinct Agenda authority values and 29,503 CFR references.
#:
#: The trailing guard is the marker's own right-hand boundary, and it is
#: load-bearing: "sec" BEGINS ordinary words. Without it "Social Security
#: Act" offers "Sec" as a marker and hands "urity" to whatever capture
#: follows, and "sections 114(a)(3)" reads the plural's own "s" as the
#: section. Every reader that demands a digit after the marker was already
#: safe by accident; :data:`_STATED_SECTION`, whose capture admits a letter,
#: was not, and published 2,350 rows of sliced-up words (measured
#: 2026-08-22). The guard belongs to the marker rather than to its readers,
#: so being safe stops being luck.
_SECTION_MARKER = r"(?:sec(?:tion)?s?\.?(?![A-Za-z])|§{1,2})"

#: What separates one list member from the next, in every list this grammar
#: expands — CFR parts, U.S.C. sections, Executive Order numbers. Leading
#: whitespace is part of the separator, not of the member.
_LIST_SEPARATOR = r"\s*(?:,\s*(?:and\s+)?|and\s+)"

#: A month, spelled or abbreviated the way the corpus writes one. Its own left
#: guard, because "Jun" and "May" sit inside longer words.
_MONTH_NAME = (
    r"(?<![A-Za-z])(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

#: A written-out calendar date: "November 1, 1987", "Oct. 12, 1984",
#: "Sept 29, 1979", "November 1,1987". **The comma inside it is the DATE's own
#: punctuation and is never a list separator** — which is the whole rule, and
#: it is what the section-list walk needs to know.
#:
#: The list walk cannot see this by itself, and the number it harvests is
#: indistinguishable from a section by shape. Refusing four-digit year-like
#: numbers would refuse REAL sections, and the sharpest proof is the very
#: number this defect minted: there is no 18 U.S.C. 1987, but 42 U.S.C. 1987
#: is "Prosecution of violation of certain laws" (uscode.house.gov, verified
#: 2026-08-22), and both 42 U.S.C. 1984 and 7 U.S.C. 1987 are cited in this
#: corpus as themselves. The parenthesised repeal note is the dominant shape
#: — "18 U.S.C. 4082 (Repealed in part as to offenses committed on or after
#: November 1, 1987)" — and the year 1987 became a section of title 18. 131
#: distinct values, 896 source rows, measured 2026-08-22 over all 42,642
#: distinct authority values; every one of them a phantom.
#:
#: The parentheses are NOT part of the rule even though the commonest shape
#: has them: "31 USC 9701 Act of August 31, 1951, 65 Stat. 290" writes the
#: date bare and loses the same way. What makes the comma a date's comma is
#: the month and day in front of it, which is the same wherever it is written.
_SPELLED_DATE = re.compile(rf"{_MONTH_NAME}\.?\s+\d{{1,2}}\s*,\s*(?:1[789]|20)\d{{2}}", re.IGNORECASE)

#: "Merchant Marine Act, 1920" — an act whose own NAME carries its year across
#: a comma. The older drafting convention writes the year that way where the
#: modern one writes "of 1920", and the U.S. Code's own headings keep it:
#: the Shipping Act, 1916, the Merchant Marine Act, 1920, the Revenue Act,
#: 1926, the Consolidated Appropriations Act, 2018. The comma is the name's
#: and never a list separator, which is the same rule :data:`_SPELLED_DATE`
#: states about a date's comma — two shapes, one sentence.
#:
#: 2 distinct values, 2 source rows, measured 2026-08-22: "…Consolidated
#: Appropriations Act, 2018, Pub. L. 115-141…" published a section 2018 of
#: title 22. The word "Act" is required, so a bare "…, 2018" — which may
#: genuinely list a section — is untouched.
_ACT_NAMED_YEAR = re.compile(r"\bAct\s*,\s*(?:1[789]|20)\d{2}", re.IGNORECASE)

#: Every shape whose internal comma belongs to what wrote it. A list walk
#: consults them together because the question it asks is one question.
_COMMAS_THAT_BELONG_TO_A_NAME: tuple[re.Pattern[str], ...] = (_SPELLED_DATE, _ACT_NAMED_YEAR)

#: Every dash spelling (hyphen, non-breaking hyphen, figure dash, en dash, em
#: dash, horizontal bar, minus sign) collapses to "-" before matching — one
#: character for one character, so spans still index the original text.
#: U+0096/U+0097 are the Windows-1252 en/em dash bytes surviving a bad decode
#: as C1 control characters — "PL 105\x96261" is PL 105-261.
#:
#: **They are not scoped to the authority field**, which is what an earlier
#: spelling of this comment claimed, and the correction it was given was
#: itself wrong. Re-measured 2026-08-31 by scanning the bytes of all 60 pinned
#: editions and attributing each occurrence to its enclosing element:
#: **1,407 occurrences TOTAL** (1,090 × U+0096, 317 × U+0097) in 28 of the 60
#: files, across **11 Agenda elements INCLUDING this one** — ABSTRACT 450
#: (439 in its own text plus 11 inside the HTML its CDATA carries, e.g.
#: "NDAA\x9610 (Pub. L. 111\x9684)" inside a `<p>`), ADDITIONAL_INFO 337,
#: RULE_TITLE 218, **LEGAL_AUTHORITY 202**, LEGAL_DLINE_OVERALL_DESC 61,
#: STMT_OF_NEED 58, ALTERNATIVES 24, COSTS_AND_BENEFITS 20, LEGAL_BASIS 20,
#: TTBL_ACTION 15, DLINE_DESC 2. Excluding LEGAL_AUTHORITY leaves **1,205
#: across the other 10** — so "1,407 across 11 OTHER elements" double-counted
#: this field into a total it is part of.
#:
#: What the authority field itself carries, measured the same day and the same
#: way: **195 `<LEGAL_AUTHORITY>` elements over 91 distinct values** (202
#: occurrences, several values carrying two), which the built table expands to
#: 250 rows over 90 distinct ``authority_text`` values. This is the
#: corpus-wide mojibake ``unified_agenda_editions`` names, not a defect of
#: citations. It changes nothing here: no identity this grammar reads is
#: affected either way, because every dash spelling folds through this SAME
#: translation table wherever a citation shape consumes it. The nine spellings
#: are ``schemas.tables.DASH_SPELLINGS`` (decision 30), the list the U.S. Code
#: tables fold their section keys by, so a citation and a table row cannot fold
#: a dash two ways.
_DASHES = str.maketrans(dict.fromkeys(DASH_SPELLINGS, "-"))

# --------------------------------------------------------------------------- #
# CFR

#: A part's or section's printed HEADING after a dash: "30 CFR part
#: 886--State and Tribal Reclamation Grants", "10 CFR Part 33—Specific
#: Domestic Licenses" (the em dash folds to one hyphen). One or two dashes, at
#: most one space, then a capital followed by a lower-case letter, which no
#: part or section number carries: the letter a number carries is lower case
#: ("15a") or a lone capital ("7 CFR 1940-G", a subpart). Added in spicy-docs
#: 2026-09-23: over the parsing survey's 60,000 Federal Register titles and
#: abstracts, 155 part citations were followed by one and read as no
#: coordinate at all, and 8 section citations read the heading into the
#: section ("60.5--Definitions").
_CFR_HEADING_DASH = r"-{1,2}[ \t]?(?-i:[A-Z][a-z])"

#: A section's inner dots and hyphens belong to its name ("60.5-1"); a
#: trailing one is the sentence's punctuation, and a hyphen that opens a
#: heading is the heading's.
_CFR_SECTION_CAPTURE = rf"[A-Za-z0-9](?:(?:(?!{_CFR_HEADING_DASH})[A-Za-z0-9.-])*[A-Za-z0-9])?"

# Capture the whole token before interpreting its hyphens. Title 41 has
# compound parts, including plural lists of them; elsewhere a plural label
# can state a numeric part range. Neither licenses a shorter numeric prefix.
# One space may follow an inner hyphen -- "41 CFR 102- 3.140", "40 CFR Parts
# 1500- 1508": 66 such citations in the survey's Federal Register texts, all
# read as no coordinate until 2026-09-23 -- and :func:`_canonical_part`
# closes it, because a part's name holds no space. A heading may follow.
_CFR_PART_CAPTURE = rf"\d+[A-Za-z]?(?:-[ \t]?\d+[A-Za-z]?)*(?:(?![\w-])|(?={_CFR_HEADING_DASH}))"

#: The word naming the unit a CFR number belongs to. "Part" and "section" are
#: different units but one syntactic slot, and the CFR writes both.
#:
#: "pts." was missing until 2026-08-22 and is now read. The GPO Style Manual
#: ch. 9 publishes "pt., pts." as the standard abbreviations and real
#: citations use it ("7 C.F.R. pts. 300, 319" at 60 FR 50379, 50381), so the
#: gap was never a judgement that the spelling is unreal — it was the fear of
#: what reading it would DO to the one such value the Agenda's CFR field
#: carries, "16 CFR pts. 0-4", where a part range would have yielded part "0".
#: The item reader now preserves that range as two endpoints.
_CFR_UNIT_LABEL = rf"(?:parts?|pts?\.?|{_SECTION_MARKER})"

# The title accepts leading zeros deliberately; the verdict falls on the
# integer (07 -> 7 possible, 00 -> 0 impossible). The offset-matching hazard
# the ancestors' [1-9] guarded against is carried by _LEFT alone.
_CFR_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?(?![A-Za-z_])"
    rf"\s*(?P<label>{_CFR_UNIT_LABEL})?\s*",
    re.IGNORECASE,
)

#: "title 40, part 60" / "40 CFR part 60" — the spelling that names the part
#: with a keyword. Ported from citations.py with one tightening: the ancestor
#: made BOTH the word "title" and "CFR" optional, so bare "5, part 2" in prose
#: fabricated title 5 part 2. Here at least one of the two anchors must be
#: present — a number and the word "part" alone name nothing.
#: The Code names itself longhand too: "title 36, Code of Federal
#: Regulations, chapter XII" carries no "CFR" for the abbreviation grammars.
_CFR_LONGHAND = re.compile(
    rf"{_LEFT}title\s+(?P<title>\d+),?\s+Code\s+of\s+Federal\s+Regulations"
    r"(?:,?\s*(?P<label>parts?|pt\.?)\s*)?",
    re.IGNORECASE,
)

_CFR_TITLE_PART = re.compile(
    rf"{_LEFT}(?:"
    rf"title\s+(?P<title>\d+)\s*[,;:-]?\s*(?:C\.?\s*F\.?\s*R\.?\s*)?"
    rf"|(?P<title_cfr>\d+)\s*[,;:-]?\s*C\.?\s*F\.?\s*R\.?\s*"
    r")(?P<label>parts?|pt\.?)\s+",
    re.IGNORECASE,
)

#: One further list item after a citation: ", 61", ", and 63", "and 63".
#: The negative lookahead is citations.py's list-tail lesson applied here: a
#: number that LEADS ANOTHER CITATION is never a list member, so
#: "17 CFR 240, 15 U.S.C. 78c" does not fabricate a part 15.
_CFR_LIST_ITEM = re.compile(
    rf"{_LIST_SEPARATOR}(?=\d)",
    re.IGNORECASE,
)

_CFR_COORDINATE = re.compile(
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?"
    rf"(?![\w]|\.[A-Za-z0-9]){_ANOTHER_CITATION_AHEAD}",
    re.IGNORECASE,
)
_CFR_RANGE_CONNECTOR = re.compile(r"\s+(?:(?i:to|through)\b\s*|-\s+)")
_CFR_UNREAD_TOKEN = re.compile(r"[\w.]+(?:[ \t]*-[ \t]*[\w.]+)*-?(?:\([^()\s]+\))*|(?:\([^()\r\n]+\))+")
_CFR_OTHER_CITATION_GUARD = re.compile(_ANOTHER_CITATION_AHEAD, re.IGNORECASE)
# A reverse spelling still names the CFR explicitly. These only locate the
# unit label and its later title; the shared item reader must consume the body.
_CFR_REVERSE_HEAD = re.compile(rf"{_LEFT}(?P<label>{_CFR_UNIT_LABEL})\s*(?=\d)", re.IGNORECASE)
_CFR_REVERSE_OF = re.compile(r"\s+of\s+(?=title\s+\d)", re.IGNORECASE)
_CFR_REVERSE_LIST_ITEM = re.compile(rf"{_LIST_SEPARATOR}(?P<label>{_CFR_UNIT_LABEL})?\s*(?=\d)", re.IGNORECASE)


def _label_is_plural(label: str | None) -> bool:
    """Whether a captured unit label names more than one unit.

    A rule rather than a roster: a label is plural when it ends in "s" — after
    the abbreviation period the publisher may or may not write — or when it is
    the doubled section sign. The roster this replaced had drifted out of sync
    with the label alternation it was supposed to mirror: it listed "pts",
    which :data:`_CFR_UNIT_LABEL` cannot capture, and so tested for a spelling
    that could never arrive.
    """

    if label is None:
        return False
    return label == "§§" or label.rstrip(".").casefold().endswith("s")


#: "3 CFR, 1977 Comp., p. 123" — a Title 3 *compilation* locator, the page an
#: Executive Order was printed on, not a CFR citation. Only title 3 compiles
#: presidential documents, so only title 3 is recognized. The separator set
#: between a volume's two years is closed, not enumerated: a dash, a slash,
#: "to", "through", "thru", "and" — none of it is ever a part number.
#: Enumerating instead left "through" still minting urn:rkaf:us:cfr:3:1949.
#: "Comp." may be omitted only when a YEAR RANGE proves the shape: no CFR
#: part is ever "1966-1970", so "3 CFR, 1966-1970, p 939" diverts without
#: the word (10 authority values; before this the range's first year minted
#: a fabricated part 1971). A single Comp-less year stays undiverted —
#: "3 CFR 1990" could name a part, and refusing to choose is the rule. The
#: doubled dash in the separator is the same publisher stutter the Public
#: Law separator tolerates, and its two halves may be SPACED APART: after
#: dash normalization "3 CFR 1966 - \x961970, p 939" reads "1966 - -1970",
#: which the un-spaced spelling could not match (1 value, 1 row).
#:
#: The volume's SECOND year is abbreviated the way any span's second endpoint
#: is — GPO and Bluebook 3.2(a) drop the repeated leading digits — and the
#: National Archives titles the volumes exactly that way ("3 CFR, 1949-1953
#: Comp."), so the corpus writes both. Reading only the four-digit spelling
#: left the abbreviated one undiverted, and ``_CFR_STANDARD`` then minted the
#: volume's FIRST YEAR as a CFR part: "3 CFR 1949-53 Comp., sec 2" published
#: title 3 part 1949, "3 CFR 1954-58, Comp, p. 218" part 1954, "as amended,
#: 3 CFR 1971-75 Comp., p.586" part 1971. 4 values, 7 rows, measured
#: 2026-08-22 — and the module's own docstring already said what they are:
#: "there is no 3 CFR § 1977, and a CFR grammar that reads one fabricates a
#: citation".
#:
#: NAMED REFUSAL: "3 CFR 1981" (6 rows) stays a CFR part. A single Comp-less
#: year states nothing that separates the compilation from a part, which is
#: the rule above, and the 1981 compilation is the first ANNUAL volume — so
#: no year range can prove its shape either. Settling it needs a 1980s CFR
#: title-3 part roster this module does not carry.
#:
#: The separator between the head and the volume year is the publisher's, and
#: the publisher writes a SEMICOLON as readily as a comma: "…; 47 FR 14874;
#: 3 CFR; 1982 Comp., 166; 8 CFR part 2" is one filer's spelling of the
#: locator its own sibling values write "3 CFR, 1982 Comp., p. 166", and both
#: name the page E.O. 12356 was printed on — the value states the order and
#: the Register citation beside it. Reading only the comma left that locator
#: unmatched, and the number it carries was then harvested as a U.S.C. list
#: item (7 rows of 31 U.S.C. 166, behind "31 USC 9701"). One colon-or-
#: semicolon in the head is the whole widening; measured over all 42,677
#: distinct authority values and all 8,240 authority notes it changes two
#: values, both quoted above.
#:
#: The page LABEL is optional for the same reason and against the same
#: casualty: "3 CFR, 1949-1953 Comp, 1002" and "3 CFR, 1996 Comp. 228" write
#: the page with no "p." in front of it, and the label's absence is not a
#: statement that the number is something else. What keeps a bare number from
#: being swallowed is the guard the list grammars already spell — a number
#: that LEADS ANOTHER CITATION is not a page either, so "3 CFR, 1982 Comp.,
#: 8 CFR part 2" ends at "Comp." and leaves 8 CFR to the CFR grammar. Nine
#: authority values and one note (40 CFR 451) fill a page this way; every one
#: of them is listed in the unit's evidence, and none of them changes a page
#: that was already read.
#: The volume year, and the word that proves the number is a volume. The Office
#: of the Federal Register titled the Title 3 volumes "Comp." from 1949 on and
#: "Supp." before that — "3 CFR, 1950 Supp." is the 1950 supplement, where
#: E.O. 10096 was printed — and reading only "Comp." left five notes minting
#: CFR parts 1950, 1953, 1961 and 1965 out of volume years (34 CFR 7, 45 CFR 7,
#: 8 CFR 1215, 19 CFR 200, 29 CFR 1400, measured 2026-08-24). No authority
#: value writes "Supp." at all, so the widening is the notes' alone.
_COMPILATION_YEAR = r"(?:1[789]|20)\d{2}"
_COMPILATION_WORD = r"(?:Comp|Supp)\.?(?!\w)"
_EO_COMPILATION = re.compile(
    r"\b3\s*C\.?\s*F\.?\s*R\.?\s*[,;:]?\s*"
    # 40 CFR 110's authority note writes "3 CFR parts 1971-1975 Comp.".
    # This label is accepted only with the explicit compilation word below.
    r"(?P<part_label>parts\s+)?"
    # Judicial ordering, already recognized by SpicySearch's source reader:
    # "3 CFR 60–61 (1971–1975 Comp.)". The numbers before the volume are
    # pages, not CFR parts. Keep both written endpoints.
    r"(?:(?P<page_before>\d+)(?:\s*-\s*(?P<page_before_end>\d+))?\s*\(\s*)?"
    # The publisher may write the volume year TWICE, once as the year and once
    # as the volume: 5 CFR 10000's note reads "E.O. 12600, 52 FR 23781, 3 CFR
    # 1987, 1987 Comp., p. 235", and the first 1987 was minted as CFR part
    # 1987. Only where the SECOND number is a year the compilation word
    # follows, so an ordinary part list can never lose its head.
    rf"(?:{_COMPILATION_YEAR}\s*,\s*(?={_COMPILATION_YEAR}\s*,?\s*{_COMPILATION_WORD}))?"
    rf"(?P<start>{_COMPILATION_YEAR})"
    r"(?:"
    r"(?:\s*(?:(?:-\s*){1,2}|/|to|thru|through|and)\s*"
    # A closing year is written three ways: in full, abbreviated to its last
    # two digits, or — where the word "Comp." itself proves the shape — as
    # whatever four digits the publisher typed. "3 CFR, 1971-1075 Comp., p.
    # 793" is the 1971-1975 volume with a mis-keyed digit (2 rows), and
    # refusing it left the volume's FIRST year minted as CFR part 1971. The
    # typo is carried, not corrected: the end reads "1075".
    rf"(?P<end>{_COMPILATION_YEAR}|\d{{4}}(?=\s*,?\s*{_COMPILATION_WORD})|\d{{2}}(?!\d)))"
    rf"\s*,?\s*(?(page_before){_COMPILATION_WORD}|(?(part_label){_COMPILATION_WORD}|(?:{_COMPILATION_WORD})?))"
    rf"|\s*,?\s*{_COMPILATION_WORD}"
    # A PAGE LABEL proves the shape where the compilation word is missing, on
    # the same terms a year range does: no CFR part is ever cited "p. 235".
    # 12 CFR 602's note writes "52 FR 23781, 3 CFR 1987, p. 235" and minted
    # part 1987. A bare number after the year still proves nothing and is
    # still refused -- the label is the whole evidence.
    r"|(?(page_before)(?!)|(?(part_label)(?!)|(?=\s*,?\s*(?:pp?\.?|pages?)\s*\d)))"
    r")"
    r"(?(page_before)(?P<closing>\s*\))?|"
    rf"(?:\s*,?\s*(?:pp?\.?|pages?)?\s*(?P<page>\d+)(?!\w)"
    rf"(?:\s*-\s*(?P<page_end>\d+)(?!\w))?{_ANOTHER_CITATION_AHEAD})?)",
    re.IGNORECASE,
)


def _compilation_end(match: re.Match[str]) -> str | None:
    """The volume's closing year, with an abbreviated one spelled out.

    "1949-53" names the 1949-1953 compilation, and the two digits are the
    same abbreviation :func:`_abbreviated_span` reads in a section span: the
    repeated leading digits are dropped. Here the endpoints are YEARS, so what
    is dropped is always the century — no ambiguity and no guard beyond
    ordering, which refuses a pair that does not ascend.
    """

    end = match.group("end")
    if end is None or len(end) == 4:
        return end
    spelled = f"{match.group('start')[:2]}{end}"
    return spelled if int(spelled) > int(match.group("start")) else end


# --------------------------------------------------------------------------- #
# U.S. Code and the other authorities

# The code names itself four ways: abbreviated ("U.S.C."), written out
# ("49 U.S. Code 106"), and as either annotated edition — West's U.S.C.A.
# ("50 U.S.C.A. 4701(a)") and LexisNexis's U.S.C.S. ("38 USCS 3564",
# measured 2026-08-22). All four are the same code and read to the same
# title and section.
_USC_CODE_NAME = r"U\.?\s*S\.?\s*(?:Code\b|C\.?(?:\s*[AS]\.?)?)"

#: A section's letter suffix is ONE letter, repeated. The Code inserts a
#: section between 106 and 107 as 106a, and when the single letters run out it
#: goes 106aa, 106bb, 106ccc — never 106ab. Verified against the OLRC's own
#: USLM release for the five titles that suffix most densely (42, 20, 15, 12,
#: 7): 18,136 sections, 898 two-letter suffixes, 102 three-letter, 2
#: four-letter, and zero that mix two different letters.
#:
#: The run is UNBOUNDED, where the ancestors capped it at three. 15 U.S.C.
#: 77aaaa (Trust Indenture Act) is real and the cap truncated it to "77aaa" —
#: a token naming nothing.
_ONE_REPEATED_LETTER = "(?:" + "|".join(f"[{low}{low.upper()}]+" for low in ascii_lowercase) + ")"

#: One U.S.C. section token: digits, then a letter suffix ONLY when that
#: suffix ends the token. The trailing guard is what distinguishes a suffix
#: from the next word with its space lost — "1251et seq." is section 1251 and
#: a Latin tail, not a section named 1251et, and "6921through 6927" is section
#: 6921. Where the letters fail either test the section is the digits alone
#: and the letters stay uncovered text, which makes the row partial and leaves
#: them visible: nothing vanishes, and nothing is invented either.
#:
#: The ancestors' plain ``[A-Za-z]{0,3}`` invented tokens outright. It read
#: "6921through" as "6921thr" and "2461note" as "2461not" — strings that
#: appear in no text anywhere, and that a consumer then joined on. 46 such
#: values were published, and "et", "to" and "and" appear zero times among
#: the 319,777 numbered elements of the OLRC's five densest titles.
#:
#: NAMED REFUSAL, measured 2026-08-22: 14 tokens over 75 source rows carry a
#: LOST HYPHEN rather than a lost space — "80bll(a)" for 15 U.S.C. 80b-11(a),
#: "6bi" for 7 U.S.C. 6b-1, "1437cA" for 42 U.S.C. 1437c-1. Their digits are
#: read and their letters stay visible, and they are NOT repaired here. The
#: operator is nameable; what this module lacks is the oracle, by layering
#: (``usc_section_oracle`` imports this module, so the reverse is circular).
#: An act index, of whatever size, is not a roster of the Code: it enumerates
#: the sections a listed ACT touches, so its coverage is a property of which
#: acts were indexed and how deeply, and membership says only that some act
#: touched a section. Non-membership proves nothing, and an
#: exactly-one-survivor test against such an index can mint a wrong real
#: section — which is not hypothetical and is why the numbers below are
#: per-table rather than per-directory. Across the 13,274 pairs the tests pin
#: (the 2026-08-02 per-page index plus the source credits) 15 U.S.C. 80b-1 is
#: PRESENT and 80b-11 is absent, so "80bll" would be minted as 80b-1 — a real
#: section the citation does not mean. 80b-1 arrives from exactly one of those
#: three tables, ``usc-popular-names``; the ``usc-act-sections`` table beside
#: it holds neither, and the bulk index holds both. Three artifacts, three
#: answers, none of them about what is law. The section-existence oracle
#: (``usc_section_oracle``,
#: 2026-08-23) closes 2 of the 14 with exactly one survivor — "80bll" →
#: 80b-11, "6bi" → 6b-1 — and the other twelve reach no candidate. The
#: specimens and the 13,274-pair measurement are pinned in the tests.
_USC_SECTION_TOKEN = rf"\d+(?:{_ONE_REPEATED_LETTER}(?![A-Za-z]))?"
#: Two section tokens joined by a hyphen — which in the U.S. Code may be one
#: section's NAME ("1395w-4") or a RANGE's separator ("7401-7671q"). The
#: grammar deliberately cannot tell them apart; :func:`_usc_section_range`
#: decides by ordering, after the match. Six patterns wrote this out
#: identically, so a widening in one was a silent divergence from five.
#:
#: One space may follow the hyphen (spicy-docs, 2026-09-23): a name never
#: holds a space, so "16 U.S.C. 460l- 9" and "42 U.S.C. 288- 5" are a lost
#: space inside one section's name, and "21 U.S.C. 1901- 1908" the same lost
#: space inside a range. :func:`_usc_section` closes the space and the
#: ordering rule decides as it decides the unspaced pair -- so the first two
#: read as sections 460l-9 and 288-5, the third as a range. Reading the
#: spaced pair as a separator instead made the ordering rule's refusal leave
#: the first endpoint alone and unresolved (29 keys in the parsing survey's
#: Federal Register texts). Not where a hyphen and digits follow the second
#: token (read whole -- the group is atomic, or "2000d" would give back its
#: "d"): in "42 U.S.C. 2000d- 2000d-42" the space separates a range whose end
#: is a compound name, and :data:`_LOOSE_DASH` reads it as one.
_USC_SECTION_SPAN = rf"{_USC_SECTION_TOKEN}(?:-{_USC_SECTION_TOKEN}|-[ \t](?>{_USC_SECTION_TOKEN})(?!-\d))?"

#: :data:`_USC_SECTION_SPAN` written out so the bare-token half alone carries
#: :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` and the hyphenated-span half
#: never does — spelling the alternation rather than appending the guard
#: after the shared span, because a guard appended AFTER the span lets the
#: engine backtrack into the span's first endpoint and publish it alone: for
#: "5316-5332.2", the whole span "5316-5332" fails the guard (dot-digit
#: follows), and backtracking to "5316" alone then satisfies it (a bare
#: hyphen follows, not a dot) — matching a single section where a range was
#: written and silently dropping its end. Spelled as an alternation, the span
#: half is tried whole or not at all, so a range that reaches the dot is left
#: intact with an uncovered footnote rather than corrupted to its start.
#:
#: The bare-token half is ALSO wrapped in an atomic group, and this one is
#: not hypothetical: widening this fence to :data:`_USC_STANDARD` in
#: 2026-09-01 first shipped without it and mis-published "40 U.S.C.
#: 102.01, 322, 5331" as section "10" — the SAME backtrack, one level in.
#: ``\d+`` refused at "102" (dot-digit follows) backtracks to "10", where
#: the next character is "2", not a dot, and the guard is satisfied on a
#: PREFIX of the very number it exists to refuse. :data:`_USC_LIST_TAIL`
#: never showed this because a literal ``\b`` sits right after its own
#: section group and a digit run has no internal word boundary to backtrack
#: into — every position but the full run fails ``\b`` before the guard is
#: even reached. Nothing downstream of this combinator can rely on that
#: accident (the appendix form's section is optional and ends the pattern;
#: the transposed label and Internal Revenue Code forms end there too), so
#: the atomic group makes the protection explicit instead of borrowed.
#:
#: Which positions it actually holds up, measured by deleting it: with the
#: atomic group gone, "46 app USC 1241.1" mints appendix section 124 and
#: "40 UCS 102.01" mints 40 U.S.C. 10, and nothing else in the corpus or the
#: fixtures moves. So the group is LOAD-BEARING at exactly two slots — the
#: appendix form and the transposed label, the two that END at the section —
#: and BORROWED at the other three, each already protected by something
#: else: :data:`_USC_LIST_TAIL` has its own ``\b`` right after the section
#: group, :data:`_USC_TITLE_FORM` requires "of title N" behind it (so a
#: backtracked prefix fails the pattern rather than publishing), and the
#: anchor's row is withheld by ``_usc_leading_section_is_untruncated``
#: whatever the regex matched. A test meaning to pin this group therefore
#: has to probe one of the first two; an assertion at the anchor, the list
#: or the "of title" head passes either way.
#:
#: One combinator, in every position that reads a single section token as a
#: COMPLETE citation on its own and where refusing it costs nothing further:
#: a listed member, the appendix form (whose section is optional, so a
#: refusal there degrades to a title-only appendix citation rather than
#: losing the match), the transposed label, and the Internal Revenue Code
#: self-name. :data:`_USC_STANDARD`'s own anchor does NOT use this
#: combinator — its section is required, and a full refusal there would
#: also drop the match that seeds the list-tail walk (:data:`_USC_LIST_TAIL`
#: scans forward from wherever the anchor's OWN match ends), taking real
#: listed members down with the fabricated anchor. It reaches the identical
#: refusal a different way: see ``_usc_leading_section_is_untruncated``,
#: applied where :data:`_USC_STANDARD` and :data:`_INTERNAL_REVENUE_CODE`
#: matches become rows. A RANGE END is not one of these positions either —
#: see :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` for why.
_USC_SECTION_SPAN_UNTRUNCATED = (
    rf"{_USC_SECTION_TOKEN}-{_USC_SECTION_TOKEN}"
    rf"|{_USC_SECTION_TOKEN}-[ \t](?>{_USC_SECTION_TOKEN})(?!-\d)"
    rf"|(?>{_USC_SECTION_TOKEN}){_A_DOTTED_NUMBER_IS_A_CFR_SECTION}"
)

#: The WORDS that separate a range's endpoints, and the space around them that
#: the publisher may have lost. "thru" was known to the compilation grammar
#: and to no other, so "47 U.S.C. 151 thru 152" — properly spelled, properly
#: spaced — dropped its endpoint (9 distinct values, 35 rows). The space is
#: optional for the same reason it is optional in the Register and Statutes
#: labels: this publisher loses separator spaces, and "6921through 6927" and
#: "5 USC 551to 557" are ranges whose separator merely lost its space (21
#: further values, 36 rows).
#:
#: A bare DASH is deliberately absent here. In the U.S. Code a hyphen may be
#: part of one section's NAME ("1395w-4"), which is the ambiguity
#: :func:`_usc_section_range` exists to resolve by ordering. Admitting a bare
#: dash here takes that decision away from the ordering rule and gets it
#: wrong: "12 USC 1702-1715z-21" reads the range 1702..1715z today, and
#: becomes the single opaque token "1702-1715z" if a dash may separate.
_RANGE_SEPARATOR = r"\s*(?:to|through|thru)\s*"

#: A SPACED dash is a different matter, and is a range separator. A section's
#: name never contains a space — "1715z-21" is one token precisely because
#: nothing separates it — so whitespace on BOTH sides is what distinguishes
#: the publisher's dash-as-range ("44 USC 3308 - 3314") from the Code's
#: dash-as-name. 41 distinct Agenda values, 66 rows, stated a range this way
#: and published only its first endpoint. The compound names above are
#: untouched, because none of them is spaced.
_SPACED_DASH = r"\s+-\s+"

#: The spaced dash's two relatives, licensed by the same rule -- a section's
#: name holds neither a space nor two dashes running. A DOUBLED dash is the
#: typewriter's em dash ("44 U.S.C. 3501--3520", 27 in the parsing survey's
#: 60,000 Federal Register titles and abstracts, each read as its first
#: endpoint alone until 2026-09-23; a real em dash folds to one hyphen and is
#: read as one), and a dash with space on one side is the publisher's lost
#: space. A space AFTER a dash is usually taken first by the section token
#: (:data:`_USC_SECTION_SPAN`), because it is as often inside a name as between
#: a range's ends; it reaches this separator only where the section token
#: declines it ("2000d- 2000d-42"). The ordering rule still decides whether
#: two numbers are a range.
_LOOSE_DASH = r"(?:\s*--\s*|\s+-\s*|\s*-\s+)"

# The title accepts leading zeros like the CFR grammar: "07 USC 5602" is
# USDA's title 7 zero-padded, the identical damage class web-verified for
# CFR titles, and [1-9] silently dropped it here for a further day.
# The optional period after the title is publisher damage the Agenda writes
# as "15. U.S.C. 78w(a)"; the dot is tolerated only immediately before the
# code name, and an absurd "title" a sentence boundary might donate is still
# judged by the series bound rather than silently believed.
_USC_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>\d+)\.?\s*{_USC_CODE_NAME}"
    # A subtitle designator may sit between the code name and the sections:
    # "46 USC subtitle II 3301, 3305" (measured 2026-08-22). The designator
    # is presentation, like an act's; the sections are what is cited.
    r"(?:\s*subtitles?\s+[IVXLC]+\s*,?)?"
    rf"(?:\s*{_SECTION_MARKER})?\s*"
    # The section slot stays the bare :data:`_USC_SECTION_SPAN`, NOT
    # :data:`_USC_SECTION_SPAN_UNTRUNCATED`, though this is exactly the
    # ANCHOR position a dot-truncated CFR regulation number reaches ("26 USC
    # 1.104-1(c)" truncates to section "1", the wrong section, at a
    # resolutely real one — 26 U.S.C. § 1 exists). Refusing the MATCH here
    # would refuse the citation :data:`_USC_LIST_TAIL` anchors its own scan
    # from, taking real listed members down with the fabricated section
    # ("40 U.S.C. 102.01, 322, 5331" would lose 322 and 5331 along with the
    # truncated 102). The refusal is applied instead where this match becomes
    # a row — ``_usc_leading_section_is_untruncated``, just below the read
    # loop — so the match still stands to seed the list walk and only the
    # fabricated section is withheld.
    rf"(?P<section>{_USC_SECTION_SPAN})"
    # A spelled range tail: "7401 to 7671q". The hyphenated spelling is
    # already inside ``section`` (a hyphen is also part of the section
    # grammar, so it has to be). Whether either spelling is really a range is
    # decided by the ordering rule, never by the separator's shape.
    #
    # The endpoint is a SPAN, not a bare token, because the Code numbers a run
    # of inserted sections with a compound name and a range may end on one:
    # "16 U.S.C. 460k to 460k-4" is the Refuge Recreation Act entire, and a
    # bare-token endpoint captured "460k" and left "-4" behind, so the pair
    # did not ascend and the end was dropped. 43 values / 491 rows.
    #
    # The endpoint carries the same guard a list member does: a number that
    # LEADS ANOTHER CITATION is not an endpoint either. Without it
    # "7 U.S.C. 6501 - 7 U.S.C. 6524" read the "7" of the second citation as
    # the range's end and swallowed the citation behind it.
    #
    # A PINPOINT may sit between the section and the range word: "42 U.S.C.
    # 405(d) to 506 (h)" is a range from 405 to 506 with a subsection named at
    # each end, and the parenthesis broke the adjacency the tail needs. 57
    # values / 249 rows stated a range this way and published no end. It is
    # tolerated INSIDE this group and nowhere else, so a subsection with no
    # range behind it is still uncovered text and its row is still "partial" --
    # "42 USC 9608 (b)" is the module's own worked example of that. The
    # endpoint's OWN trailing pinpoint is deliberately left uncovered for the
    # same reason.
    #
    # AND THE GUARD IS ATOMIC, which is the whole of the fix for a defect the
    # guard alone made worse. "12 U.S.C. 1422 to 12 U.S.C. 1424": the endpoint
    # matched "12", the guard refused it — and the engine then BACKTRACKED the
    # endpoint to the single digit "1", where the guard is satisfied because
    # "2 U.S.C." is not a code name. The match consumed " to 1", the scan
    # resumed inside "12", and ``_LEFT`` refused to start a citation after a
    # digit — so the whole second citation vanished. 19 values / 63 rows, every
    # one of them a citation the filer wrote in full. An atomic group refuses
    # to give back what it matched, so the tail now fails as a whole and the
    # second citation is read where it stands.
    rf"(?:(?:\s*\([0-9A-Za-z]{{1,4}}\))*(?:{_RANGE_SEPARATOR}|{_SPACED_DASH}|{_LOOSE_DASH})"
    rf"(?P<range_end>(?>{_USC_SECTION_SPAN}))"
    rf"{_ANOTHER_CITATION_AHEAD})?",
    re.IGNORECASE,
)

#: The word that says the number behind it is a CHAPTER, spelled every way the
#: corpus can. Named once because two readers need the same spelling:
#: :data:`_USC_CHAPTER`, which types the citation, and
#: :func:`usc_token_is_chapter_qualified`, which asks whether the word still
#: governs a number further down the same list.
_CHAPTER_MARKER = r"(?:chapters?|chaps?\.?|chs?\.?)"

#: "49 U.S.C. ch. 311" — the unit above a section, spelled every way the
#: corpus can ("ch.", "Ch", "ch.13" with no space, "chapter"). A chapter
#: number never contains a hyphen, so a dash after one is always a separator
#: — but the range tail still requires a number behind it, because
#: "22 USC Ch. 34- The Peace Corps Act" cites chapter 34 and the dash there
#: is punctuation before a title.
_USC_CHAPTER = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*{_USC_CODE_NAME}"
    rf"\s*{_CHAPTER_MARKER}\s*"
    r"(?P<chapter>\d+[A-Za-z]?)\b"
    # The word separators are the section grammar's; the DASH is this
    # grammar's alone, and safe here for the reason the section grammar
    # cannot have it — a chapter number never contains a hyphen.
    rf"(?:(?:{_RANGE_SEPARATOR}|\s*-\s*)(?P<chapter_end>\d+[A-Za-z]?)\b)?",
    re.IGNORECASE,
)

#: A section list under one title: "42 U.S.C. 1395, 1396, 1397". The lookahead
#: stops the expansion at a number that leads another citation form, so
#: "5 U.S.C. 301, 117 Stat. 429" never lists section 117.
#:
#: This list is SCANNED across a window, where the CFR and Executive Order
#: lists are walked anchored, item touching item. That looks like drift and is
#: not: the authority column writes subsection parentheticals, "note" tails
#: and spelled ranges INSIDE its section lists — "22 U.S.C. 214, 214 note,
#: 1475e, 2504(a), 4201" — and an anchored walk stops dead at the first one.
#: Re-walking these anchored was measured against the corpus: 1,168 distinct
#: values, 19,167 rows, would lose a real listed section. Two shapes, two
#: rules.
#:
#: An APPENDIX citation seeds this list too, and did not until 2026-08-22:
#: only ``_USC_STANDARD`` matches were seeds, so "46 app USC 808, 839"
#: published 808 alone. Both are real appendix sections of the Shipping Act,
#: 1916 (46 App. U.S.C. 808 "Registration, enrollment, and licensing of
#: vessels purchased, chartered, or leased"; 839 "Approvals by Secretary" —
#: uscode.house.gov, 1999 edition), so the omission dropped citations rather
#: than declining ambiguous ones. 15 distinct values, 37 source rows, 45 rows
#: gained and none lost. A listed member inherits the appendix flag.
#: The section slot here is :data:`_USC_SECTION_SPAN_UNTRUNCATED` — this
#: reader's own bare-token guard was where the alternation was first spelled
#: out (2026-08-24) and the widening of 2026-09-01 promoted it to the shared
#: combinator every "single token is a complete citation" position now uses;
#: see :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` for why the span half never
#: carries the guard.
#:
#: A LISTED MEMBER MAY BE A RANGE, and this pattern had no tail for one until
#: 2026-08-24: "20 U.S.C. 1406, 1431 through 1444" published 1406 and 1431 and
#: dropped 1444, while the identical range standing alone kept it. 191 values /
#: 3,880 rows, the largest of the five range shapes. The tail is the standard
#: form's, character for character — the same separators, the same pinpoint
#: tolerance, the same atomic endpoint and the same "another citation ahead"
#: guard — because a listed range and a leading one are the same statement in
#: two positions, and a tail that differed would be a second opinion about
#: what a range is.
_USC_LIST_TAIL = re.compile(
    rf"(?:,|\band\b|\bor\b)\s*(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})\b"
    rf"{_ANOTHER_CITATION_AHEAD}"
    rf"(?:(?:\s*\([0-9A-Za-z]{{1,4}}\))*(?:{_RANGE_SEPARATOR}|{_SPACED_DASH}|{_LOOSE_DASH})"
    rf"(?P<range_end>(?>{_USC_SECTION_SPAN}))"
    rf"{_ANOTHER_CITATION_AHEAD})?",
    re.IGNORECASE,
)

#: A Regulation Identifier Number — the Agenda's own name for a rulemaking,
#: four digits for the agency, then two letters and two digits. It is not a
#: citation, and its agency prefix is not a section: a filer who mentions a
#: sibling rulemaking inside a citation list ("…, 3235-AE17.") puts a bare
#: four-digit number behind a comma, and the list walk above reads ", NNNN" as
#: another listed section under whatever title the last citation named. SEC RIN
#: 3235-AH12's Fall 1998 continuation minted 15 U.S.C. 3235 exactly this way.
#:
#: Uppercase only, which is the publisher's own spelling: measured over all
#: 42,642 distinct authority values and all 98 ADDITIONAL_INFO continuations,
#: every RIN-shaped token written anywhere is uppercase and there are two of
#: them ("1904-AG07: 42 U.S.C. 16251", where the token LEADS the value and no
#: list separator precedes it, and the 3235-AH12 continuation).
#:
#: The sibling shape was measured and REFUSED. A Federal Register document
#: number is ``\d{2,4}-\d{3,6}``, and 1,536 rows over 455 distinct
#: (value, title, section) triples in the pinned table are that shape — every
#: one of them a real U.S.C. RANGE the standard form read ("50 U.S.C.
#: 4801-4852", 256 rows; "28 U.S.C. 509-510", 48; "42 U.S.C. 6291-6309", 22).
#: Fencing that shape would delete real citations, so it is not fenced. Two
#: letters between the hyphen and the trailing digits are what make this one
#: unambiguous.
_RIN_TOKEN = re.compile(r"(?<![0-9A-Za-z])\d{4}-[A-Z]{2}\d{2}(?![0-9A-Za-z])")

#: "section 553 of title 5" — the spelling statutes themselves use, with the
#: plural-list variant ("sections 3501, 3502 and 3503 of title 44") from
#: SpicySearch, whose gap here was found by a search-quality benchmark. A bare
#: "section 553" with no "of title" tail stays undetected rather than guessed.
#: The head and each listed item carry the same dot refusal as every other
#: single-token reading (see :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION`),
#: unmeasured against a real specimen — no corpus value pairs "of title" with
#: a dotted number — but the same shape reaches the same class of citation
#: through this reader as through :data:`_USC_STANDARD`, and a rule that held
#: only where a specimen happened to exist would be luck, not a rule.
#:
#: LATENT SHAPE, stated rather than built for. The refusal sits INSIDE the
#: pattern at the ``first`` slot, so a dotted FIRST member drops the whole
#: citation and every real member behind it: "sections 102.01, 322 of title
#: 40" reads nothing, where the same damage at :data:`_USC_STANDARD`'s
#: anchor withholds the fabricated row alone and keeps 322. That collateral
#: loss is exactly what the anchor's out-of-regex refusal exists to avoid,
#: and the same machinery is NOT built here, because the position is empty:
#: replaying this reader with and without the guard over all 42,677 distinct
#: authority values and all 8,240 notes changes 0 texts (measured
#: 2026-09-01), and every one of the 41 values the widening does remove a
#: pair from is a truncated prefix that loses nothing real. Structure earns
#: its keep, so the refuse-the-whole-citation behaviour is PINNED by a
#: fixture rather than fixed by machinery nothing asks for — the first real
#: specimen fails that fixture and forces the conversation instead of
#: landing silently.
_USC_TITLE_FORM = re.compile(
    rf"{_LEFT}{_SECTION_MARKER}\s*"
    rf"(?P<first>{_USC_SECTION_SPAN_UNTRUNCATED})"
    rf"(?P<items>(?:{_LIST_SEPARATOR}{_USC_SECTION_TOKEN}{_A_DOTTED_NUMBER_IS_A_CFR_SECTION})*)"
    rf"\s+of\s+title\s+(?P<title>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
_USC_TITLE_FORM_ITEM = re.compile(
    rf"{_LIST_SEPARATOR}(?P<section>{_USC_SECTION_TOKEN}{_A_DOTTED_NUMBER_IS_A_CFR_SECTION})"
)

#: "50 U.S.C. app. 2401" — a section of a title's APPENDIX, which is a real
#: place (the Export Administration Act lived in 50 U.S.C. app. for decades)
#: and not the same place as the title proper. 3,870 Agenda authorities cite
#: appendices; reading them as plain title-50 sections would merge two
#: different bodies of law, so the appendix is carried as its own flag.
#: The marker naming a title's appendix, in any case — "5 USC APP" (8 rows,
#: measured 2026-08-22) names the same appendix the lowercase spelling does.
#: The case fold is scoped to the marker: the code name beside it stays
#: case-sensitive, which is this pattern's own capitalization-as-evidence.
_APPENDIX_MARKER = r"(?i:app(?:endix|x?\.?)?)"

#: KNOWN GAP, measured 2026-08-24, stated rather than fixed in passing: this
#: pattern has NO ``range_end`` tail where :data:`_USC_STANDARD` has one, so a
#: SPELLED range inside an appendix citation loses its far end. "49 App. U.S.C.
#: 1 to 85 (1988)" publishes ``usc_section`` 1 and ``usc_section_end`` NULL,
#: while the same range written "49 USC 1 to 85 (app)" — where the marker
#: trails and the standard form matches — keeps 85. Over the 2,548 rows the
#: recodification tables are asked about, 162 rows in 33 distinct texts write a
#: range word with no captured end, 144 of them matched here; downstream that
#: is 144 rows whose span answer cannot fire at all (see
#: ``unified_agenda_parquet._judge_usc_sections`` and RIN 1902-AF39, the
#: visual review of 2026-08-23 § J row 4). Closing it means giving this pattern
#: the same tail and the same ORDERING rule that decides whether a hyphen is a
#: range — a change to what 3,870 appendix rows parse to, which is its own unit
#: with its own diff, not a line added here.
#: The section slot is optional, and where present carries the same dot
#: refusal :data:`_USC_STANDARD` does: "46 app USC 1241.1" truncated to
#: appendix section 1241 — a further Coast Guard/MARAD regulation number
#: read as a Code section, measured with the anchor fix of 2026-09-01 (see
#: :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION`). Because the group is
#: optional, a refused reading falls back to the title-only appendix
#: citation rather than failing the whole match — the appendix is still
#: real even when the section number offered for it is not.
_USC_APPENDIX = re.compile(
    rf"{_LEFT}(?P<title>\d+)\s*"
    # The appendix marker appears on either side of the code name: "50 U.S.C.
    # app. 2401" and "50 app USC 2071" both occur in the Agenda.
    rf"(?:{_USC_CODE_NAME}\s*(?:§{{1,2}}\s*)?{_APPENDIX_MARKER}"
    rf"|{_APPENDIX_MARKER}\s*{_USC_CODE_NAME})\s*"
    rf"(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})?",
)

#: "123 F 3d 1460", "141 F.3d 662", "550 U.S. 544", "128 S. Ct. 2131" — case
#: reporter citations. A different identifier family from everything above:
#: volume-reporter-page locates a decision, not an enactment. The reporter
#: token is the anchor and is matched from a closed set, because "F" and "S"
#: are letters prose uses freely.
#:
#: This pattern needs no year and must not grow a requirement for one — the
#: corpus writes yearless case citations ("Natural Resources Defense Council
#: v. U.S. Forest Service, 421 F.3d 797") and yearless is not what went
#: wrong. What went wrong was a value carrying NEITHER a case name nor a
#: year, which is a U.S.C. citation with a lost C; those never reach here,
#: because ``dropped-c-in-usc-label`` rewrites the whole value first.
_CASE_REPORTER = re.compile(
    _guarded(
        r"(?P<volume>[1-9]\d{0,3})\s+"
        r"(?P<reporter>F\.?\s?(?:2d|3d|4th)|F\.?\s?Supp\.?\s?(?:2d|3d)?|U\.\s?S\.|S\.\s?Ct\.|Cl\.?\s?Ct\.?)"
        r"\s+(?P<page>[1-9]\d{0,4})"
    )
)
#: "318 US 363 (1943)" — the U.S. Reports with its periods lost. Periodless
#: "US" is ambiguous on its own: "50 US 2401" is 50 U.S.C. 2401 with a lost
#: C, not a case. The parenthesized year is what disambiguates, and the year
#: is REQUIRED here, so the yearless form stays refused.
#:
#: The reason written here used to be "case citations carry one, code
#: citations never do". That is FALSE, and loudly: the Bluebook cites a
#: specific EDITION of the Code exactly that way, and this corpus carries 247
#: such rows across 59 distinct values — "49 USC app 1 to 85 (1988)" (22
#: rows), "28 U.S.C. 2461 note (1990)" (13), "5 U.S.C. 301 (2018)" (8) —
#: against a total case-citation population of 107 rows. A year is not a case
#: marker anywhere in US citation practice.
#:
#: What actually holds the fence is narrower and empirical: a periodless "US"
#: with no C ANYWHERE, plus a year. Measured over all 42,642 distinct values,
#: every value reaching this pattern is one of the two U.S. Reports citations
#: the Agenda carries, and every code citation written periodless ("50 US
#: 2401 et seq", "42 US 2201", "15 US 1392", "30 US 820", "49 US 44719")
#: carries no year at all. A value that were BOTH — a lost C and an edition
#: year — would be misread here, and none exists. That is a measurement, not
#: a guarantee, and it is why this pattern must not be widened to admit a
#: "USC" label: see the refusal of "318 USC 363 (1942)" in the tests.
_CASE_US_PERIODLESS = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s+US\s+(?P<page>[1-9]\d{{0,4}})\s*\((?:1[789]|20)\d{{2}}\)"
)

#: "Reorganization Plan No. 3 of 1970" — a real authority type: plans made
#: under the Reorganization Acts carry the force of law and the Agenda cites
#: ~1,300 of them.
_REORGANIZATION_PLAN = re.compile(
    r"[Rr]eorg(?:anization)?\.?\s*Plan\s*(?:No\.?\s*)?(?P<number>\d+)\s*of\s*(?P<year>(?:1[89]|20)\d{2})"
)

#: Presidential proclamations: "Proclamation 10908", "Presidential
#: Proclamation No. 7383", "Proc 10414". The numbered series ran past 11037
#: by mid-2026 (Federal Register proclamations collection; Proclamation 10998
#: is the 2026 travel restriction), so the bound is generous. Capital P
#: required — "proc" is a prose fragment.
_PROCLAMATION = re.compile(
    _guarded(r"(?:Pres(?:idential|\.)?\s+)?Proc(?:lamation)?\.?\s*(?:No\.?\s*)?(?P<number>[1-9]\d{0,4})")
)

#: Presidential memoranda and notices are date-identified, not numbered:
#: "Presidential Memorandum of January 31, 2014", "Notice of August 3, 2000
#: (65 FR 48347)" — the latter is the continuation-of-national-emergency
#: form that appears bare in the Agenda's authority field. The full
#: Month-day-year shape is required so prose "notice of default" reads
#: nothing.
_PRESIDENTIAL_MEMORANDUM = re.compile(
    r"Presidential\s+Memorandum\b|Memorandum\s+for\s+the\s+(?:Attorney\s+General|Secretary)"
)
_PRESIDENTIAL_NOTICE = re.compile(
    r"Notice\s+of\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+(?:1[89]|20)\d{2}"
)
#: Presidential directives: "Homeland Security Presidential Directive 12",
#: "HSPD-12", "Presidential Directive, John F. Kennedy (Nov. 10, 1961)".
#: Typed by kind alone, the same convention as memoranda and notices — the
#: identifying number or date stays visible in the original text. The bare
#: series tokens demand uppercase and a number, per the bare-"EO" rule.
_PRESIDENTIAL_DIRECTIVE = re.compile(
    r"(?:(?:Homeland\s+Security|National\s+Security)\s+)?Presidential\s+(?:Decision\s+)?Directive"
    r"|\b(?:HSPD|NSPD|PDD)\s*-?\s*\d{1,3}\b"
)
#: The three date-identified presidential kinds. Each carries a kind and no
#: number, so a match never covers the value that states the date.
_PRESIDENTIAL_DOCUMENT_KINDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_PRESIDENTIAL_MEMORANDUM, "memorandum"),
    (_PRESIDENTIAL_NOTICE, "notice"),
    (_PRESIDENTIAL_DIRECTIVE, "directive"),
)

#: Administrative orders: a department head's own instruments, cited as
#: authority. "Secretary's Order 3-2007", "DHS Delegation No. 0170.1",
#: "Department of Commerce Department Organization Order 10-4". DHS
#: Delegation 0170.1 is cited as legal authority in Federal Register
#: rulemaking documents, which is what licenses the family. The number
#: shapes are the observed set: dotted ("0170.1"), dashed ("3-2007", "4-75").
#:
#: A PARENTHESIZED NUMBER BEHIND IT IS NOT PART OF IT. This capture read
#: "0170.1(92)" as a revision of the instrument and so minted a second
#: identity for one delegation: 8 values / 61 rows, measured 2026-08-22. The
#: corpus refutes the revision reading in its own words — the same office
#: writes "DHS Delegation No. 0170.1, para (92)" (15 rows), "DHS Delegation
#: 0170.1, paragraph 92" (9), "DHS Delegation No. 0170.1, paragraph (92)(b)"
#: (3) and "DHS Delegation No 0170.1 (92)(a), (92)(b)" (4, spaced, and
#: therefore already read as 0170.1) — so the parentheses hold a PARAGRAPH of
#: the delegation, the way a subsection sits under a section. And the bare
#: instrument is filed 350 times against 61 for the parenthesised spellings.
#: The paragraph stays uncovered text, which leaves those rows partial rather
#: than "ok" and keeps the characters visible.
#: The Secretary alternative names the office when the publisher does:
#: "Secretary of Labor's Order 1-2011", "Secretary of the Air Force Order
#: 111.1", possessive or not, curly or straight apostrophe (130 Agenda rows
#: cite these; the earlier spelling set read none of them). The number
#: tolerates a space after its dash ("No. 1- 87") — stripped on capture.
#:
#: An order's number, written once because the list tail below spells the same
#: shape and a widening in one would be a silent divergence from the other.
#:
#: The trailing guard is the number's own right-hand boundary, and it is
#: load-bearing in the list tail: without it ``\d+`` BACKTRACKS out from under
#: the next-citation lookahead. "Secretary's Order No. 3-81, 46 FR 31117" read
#: "4" as a listed order and left "6 FR 31117" for the lookahead to approve —
#: a number that appears nowhere in the string. This is the module's own
#: inner-boundary lesson at a third site: a citation's outer boundary says
#: nothing about its inner ones, and a lookahead placed after a backtrackable
#: token guards nothing.
_ADMIN_ORDER_NUMBER = rf"\d+(?:[-.]\s?\d+)*[A-Za-z]?{_RIGHT}"

_ADMINISTRATIVE_ORDER = re.compile(
    r"(?P<kind>Secretar(?:y(?:\s+of\s+(?:the\s+)?[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)?(?:['’]s)?|ial)\s+Orders?"
    r"|Delegation(?:\s+Orders?)?|(?:Department(?:al)?\s+)?Organization\s+Orders?|Administrative\s+Orders?)"
    r"\s*(?:,\s*)?(?:Nos?\.?\s*)?"
    rf"(?P<number>{_ADMIN_ORDER_NUMBER})"
)

#: One further order after a citation: "and 14-75", ", 3302". Walked ANCHORED,
#: item touching item, the shape the Executive Order list takes — and it needs
#: the same next-citation lookahead for the same reason, because this family's
#: commonest neighbour is a Federal Register locator: "Secretary's Order No.
#: 3-81, 46 FR 31117" lists no order 46, and "Secretary of Labor Order 1-2012
#: and 29 CFR 1911" lists no order 29.
#:
#: Without this walk a plural label listed in vain: "Secretary's Orders 4-75
#: and 14-75" (17 rows) published 4-75 alone, where both are real and distinct
#: Department of Labor orders — 4-75 "Manpower Programs" (40 FR 18515), still
#: cited as authority in 20 CFR parts 609, 614, 616 and 625; 14-75 of November
#: 12, 1975, which reorganized the Manpower Administration into the Employment
#: and Training Administration.
#:
#: No plural label is demanded, for the reason the Executive Order list gives:
#: this is the Agenda's structured field, where the whole value is the
#: citation. Measured over all 42,642 distinct authority values, the lookahead
#: is what does the work — every singular-label value in the corpus is
#: followed by a Register citation and stops there.
_ADMINISTRATIVE_ORDER_LIST_TAIL = re.compile(
    rf"{_LIST_SEPARATOR}(?P<number>{_ADMIN_ORDER_NUMBER}){_ANOTHER_CITATION_AHEAD}"
)

#: Treaty series, per Bluebook rule 21.4.5's own preference list: U.S.T.
#: (United States Treaties, 1950-1984, volume-page), T.I.A.S. (numbered),
#: U.N.T.S. (volume-page), Senate Treaty Documents (congress-number). The
#: series tokens are uppercase in every citation manual; lowercase is prose.
#: Their volume bounds LOOK like a copy-paste divergence and are not: U.S.T.
#: ceased at volume 35 in 1984, while the U.N. Treaty Series is past 3,000
#: volumes and still running. Each bound is its own series' fact.
_TREATY_UST = re.compile(_guarded(r"(?P<volume>[1-9]\d{0,2})\s+U\.?\s?S\.?\s?T\.?\s+(?P<page>[1-9]\d{0,4})"))
_TREATY_TIAS = re.compile(_guarded(r"T\.?\s?I\.?\s?A\.?\s?S\.?\s*(?:No\.?\s*)?(?P<number>[1-9]\d{0,5})"))
_TREATY_UNTS = re.compile(_guarded(r"(?P<volume>[1-9]\d{0,3})\s+U\.?\s?N\.?\s?T\.?\s?S\.?\s+(?P<page>[1-9]\d{0,4})"))
_TREATY_SENATE_DOC = re.compile(
    _guarded(r"S\.?\s*Treaty\s+Doc(?:ument)?\.?\s*(?:No\.?\s*)?(?P<congress>\d{2,3})-(?P<number>\d{1,3})")
)
#: Read in the Bluebook's own preference order, which is also the order the
#: rows are published in.
_TREATY_SERIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_TREATY_UST, "UST"),
    (_TREATY_UNTS, "UNTS"),
    (_TREATY_TIAS, "TIAS"),
    (_TREATY_SENATE_DOC, "S. Treaty Doc."),
)

#: "R.S. 463" — the Revised Statutes of 1874, the first codification of
#: federal law and still positive law where never repealed: R.S. 161 is the
#: housekeeping statute (5 U.S.C. 301), R.S. 463 and 465 ground the Bureau
#: of Indian Affairs' rules (25 U.S.C. 2 and 9). 107 Agenda authority rows
#: cite them bare. Uppercase required — lowercase "rs" is prose, and _LEFT
#: keeps "IRS 463" from donating its tail.
_REVISED_STATUTES = re.compile(_guarded(rf"R\.?\s?S\.?\s*,?\s*{_SECTION_MARKER}?\s*(?P<section>[1-9]\d{{0,3}})"))

#: The District of Columbia Code, cited as legal authority by the agencies
#: that administer D.C. functions (the Bureau of Prisons and Parole
#: Commission under the Revitalization Act). Two spellings occur: the
#: modern title-section compound ("D.C. Code 24-131(a)(1)", "D.C. Official
#: Code sec. 22-4151") and the older title-first form ("26 DC Code 102").
#: 166 Agenda rows. Uppercase D.C. and capitalized Code required.
_DC_CODE_ANCHOR = re.compile(rf"(?:{_LEFT}(?P<title>\d{{1,2}})\s+)?D\.?\s?C\.?\s+(?:Official\s+)?Code\b")
#: A modern D.C. Code section is title-section ("24-131", "24-403.01");
#: subsection parentheticals are consumed but, as everywhere else, dropped.
_DC_CODE_SECTION = re.compile(
    rf"\s*(?:,?\s*(?:and\s+)?)?{_SECTION_MARKER}?\s*"
    r"(?P<section>\d{1,2}-\d{1,4}(?:\.\d{1,3})?)(?:\([^()]{1,8}\))*"
)
_DC_CODE_BARE_SECTION = re.compile(rf"\s*{_SECTION_MARKER}?\s*(?P<section>\d{{1,4}})\b")

#: "212 DM 13" — the Interior Department's Departmental Manual, its own
#: directives system, cited as authority the way Secretary's Orders are.
#: The compound part-DM-chapter is the citation and is kept verbatim; a
#: subsection parenthetical ("130 DM 7.3(c)") is dropped like every other.
#: Uppercase DM required — lowercase "dm" is prose.
_DEPARTMENTAL_MANUAL = re.compile(_guarded(r"(?P<part>\d{1,3})\s+DM\s+(?P<chapter>\d{1,3}(?:\.\d{1,3})?)"))

#: Departmental directives systems beyond Interior's, each web-verified
#: 2026-08-22 and each cited by its own department's Agenda rows: the
#: Forest Service Manual ("FSM 2320" is the wilderness-management chapter,
#: 56 rows at USDA-FS RINs), DoD Directives ("DODD 5000.35"), DOJ Orders
#: ("DOJ Order 2710.8A") and Attorney General's Orders ("AG Order
#: 1687-93"). Uppercase series tokens required, per the bare-"EO" rule.
#: Each entry is (series label, number shape, the kind published). The
#: boundary guards are applied by the table rather than written into each
#: row: four hand-guarded patterns is four chances to forget one end.
_DIRECTIVE_SYSTEMS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(_guarded(rf"(?:{series})\s*(?P<number>{number})")), kind)
    for series, number, kind in (
        (r"FSM\s", r"\d{4}(?:\.\d{1,3})?", "Forest Service Manual"),
        (r"(?:DODD|DoDD|DOD\s+Directive|DoD\s+Directive)\s", r"\d{4}\.\d{1,3}[A-Za-z]?", "DoD Directive"),
        (r"DOJ\s+Order\s", r"\d{2,5}(?:\.\d{1,3})?[A-Za-z]?", "DOJ Order"),
        (
            r"(?:AG|Attorney\s+General(?:['’]s)?)\s+Order\s*(?:No\.?\s*)?",
            r"\d{2,4}-\d{2,4}",
            "Attorney General's Order",
        ),
    )
)

#: "FAR 1.301" — the Federal Acquisition Regulation citing itself by its own
#: name. FAR 1.105-2 declares the equivalence: the regulation "may be
#: referred to as the Federal Acquisition Regulation or the FAR", and the
#: parallel citation form is "(FAR) 48 CFR 1.301" — so the FAR part IS the
#: CFR part under title 48, chapter 1, by the instrument's own declaration
#: (web-verified 2026-08-22). Whole-value only and uppercase FAR only:
#: lowercase "far" is the English word.
_FAR_SELF_CITATION = re.compile(r"^\s*FAR\s+(?P<part>\d{1,2})\.(?P<section>\d{3}(?:-\d{1,2})?)\s*$")

#: "DFARS 201.3", "DOD FAR 201.3" (12 rows) — the Defense supplement citing
#: itself, the FAR self-citation one chapter over. The Office of the Federal
#: Register publishes the equivalence in its own headings: eCFR titles 48 CFR
#: part 201 "Federal Acquisition Regulations System (DFARS Part 201)", and
#: the whole supplement is 48 CFR chapter 2, parts 201-253 (web-verified
#: 2026-08-22). The 2xx part number is therefore the CFR part, so the fence is
#: the chapter's own range: a value outside 201-253 is not the DFARS.
_DFARS_SELF_CITATION = re.compile(
    r"^\s*(?:DFARS|DOD\s+FAR|DoD\s+FAR)\s+(?P<part>2(?:0[1-9]|[1-4]\d|5[0-3]))"
    r"\.(?P<section>\d{1,4}(?:-\d{1,2})?)\s*$"
)

#: One structural designator inside a code title: "subchapter U", "part III",
#: "subtitle IV", "part 2". Title 26's subchapters are lettered, everyone
#: else's are roman or arabic, so all three alphabets are admitted — and the
#: designator word is required, which is what keeps a section number out.
_USC_DESIGNATOR = r"(?:sub)?(?:chapter|title|part)\s+(?:[IVXLC]+|\d{1,3}|[A-Z])[A-Za-z]?"

#: A whole value that names a U.S.C. title and then a STRUCTURAL DESIGNATOR
#: inside it: "26 USC subchapter U", "8 USC part 2", "49 U.S.C. subtitle IV",
#: "5 U.S.C. part III, subpart F" (29 rows, 8 spellings). A subchapter is a
#: real container and this grammar has no column for one, so the row reads as
#: the bare title it also states — partial, never "ok", exactly the posture
#: "16 USC et seq" already has, with the designation left visible in the
#: original text the way act designator tails are.
_USC_TITLE_WITH_DESIGNATOR = re.compile(
    rf"^\s*(?P<title>[1-9]\d?)\s*{_USC_CODE_NAME}\s*\.?\s*,?\s*"
    rf"{_USC_DESIGNATOR}(?:\s*,?\s*{_USC_DESIGNATOR})*\s*$",
    re.IGNORECASE,
)

#: A whole value shaped like a CFR citation whose title is OUTSIDE the CFR's
#: 50-title series but whose numbers are a perfect Federal Register
#: volume/page: "60 CFR 15845" (10 rows, the only such value in the failed
#: pool). The text's own numbers refute its claimed scheme — this is the
#: measurement that relabelled 64 timetable citations in wave 1 — and 60 FR
#: 15845 is a real page of the March 27, 1995 Register (web-verified
#: 2026-08-22), cited by NASA as authority for its 14 CFR 1214 rule. Typed
#: ``federal_register`` with the same posture as every other FR-in-the-wrong-
#: column row: partial, original text preserved.
_CFR_TITLE_IMPOSSIBLE_IS_FR = re.compile(
    r"^\s*(?P<volume>\d{2,3})\s*C\.?\s?F\.?\s?R\.?\s+(?P<page>\d{1,6})\s*$", re.IGNORECASE
)

#: A whole value that is an EO-compilation fragment with its "3 CFR" head
#: lost: "1991 Comp p 351", "Comp., p. 193" (52 rows, measured 2026-08-22).
#: Only Title 3 prints Comp. pages, so the word proves the family even
#: where the head is gone; whole-value only, so prose can never donate one.
_COMPILATION_FRAGMENT = re.compile(
    r"^\s*(?:(?P<year>(?:1[789]|20)\d{2})\s*,?\s*)?Comp\.?\s*,?\s*p{1,2}\.?\s*(?P<page>\d{1,4})\s*\.?\s*$"
)

#: A treaty or international instrument named without a series token:
#: "Convention on International Civil Aviation", "Compacts of Free
#: Association With the Federated States of Micronesia...", "Single
#: Convention on Narcotic Drugs, 1961" (86 rows over 14 distinct values,
#: measured 2026-08-22). Typed by kind alone, the presidential-memoranda
#: convention: the instrument's name stays visible in the original text and
#: no series identifier is minted. Anchored to the value's head (after an
#: article/section locator) so prose ABOUT a convention — "Chemical Weapons
#: Convention Implementation Legislation Proposed" — stays refused.
_TREATY_INSTRUMENT_NAME = re.compile(
    r"^\s*(?:[Aa]rticles?\s+\d+(?:\s+and\s+\d+)*\s+of\s+(?:the\s+)?|[Ss]ec\.?\s*\d+\s+of\s+the\s+)?"
    r"(?:(?:Single\s+)?Convention\s+on\s+[A-Z]"
    # "... Convention Act" and "... Convention Implementation" name the
    # implementing LEGISLATION, not the instrument — the Atlantic Tunas
    # Convention Act of 1975 is a statute, and typing it treaty would be
    # the mistype this lookahead refuses.
    r"|[A-Z][A-Za-z]+(?:\s+[A-Za-z]+){0,5}\s+Convention(?!\s+(?:Implementation|Act\b))\b"
    r"|Compacts?\s+of\s+Free\s+Association\b)"
)

#: "U.S. Const., Art. II, Sec. 2" — the appointments-clause citation the
#: Agenda's authority field carries 21 times. Article numbers are Roman in
#: every observed form; the damaged "US Cost" spelling stays unread rather
#: than guessed.
_CONSTITUTION = re.compile(
    r"U\.?\s?S\.?\s+Const(?:itution)?\.?,?\s*[Aa]rt(?:icle)?\.?\s*(?P<article>[IVX]+|\d+)"
    r"(?:,?\s*[Ss]ec(?:tion)?\.?\s*(?P<section>\d+[A-Za-z]?))?"
)

#: A whole field value that names a title and nothing else: "16 USC et
#: seq", "28 U.S.C.", and the inverted longhand "title 35 of the U.S.C."
#: (4 rows, measured 2026-08-22). Only a fallback — it runs when no fuller
#: grammar read anything — and only ever against the entire value, so prose
#: can never donate a bare title.
_BARE_USC_TITLE = re.compile(
    rf"^\s*(?P<title>[1-9]\d?)\s*{_USC_CODE_NAME}\s*\.?\s*(?:,?\s*et\.?\s*seq\.?\.?)?\s*$",
    re.IGNORECASE,
)
_BARE_USC_TITLE_LONGHAND = re.compile(
    rf"^\s*title\s+(?P<title>[1-9]\d?)\s+of\s+the\s+(?:{_USC_CODE_NAME}\.?|United\s+States\s+Code)\s*$",
    re.IGNORECASE,
)

#: "21 UCS 374" — the code label with its letters transposed (26 rows,
#: measured 2026-08-22; "26 UCS 7805" is the IRS's rulemaking authority
#: 26 U.S.C. 7805). Uppercase only — "UCS" is not an English word, but the
#: case is still the evidence the bare-label rule demands — and the damage
#: operator is the same adjacent transposition the corroborated corrections
#: name. No other citation label is one transposition from "UCS". The section
#: slot carries the same dot refusal as the standard label's own anchor (see
#: :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION`) — a transposed label is still a
#: U.S.C. anchor, and unmeasured against a real specimen only because no
#: corpus value happens to transpose the letters of a truncated one.
_USC_TRANSPOSED_LABEL = re.compile(rf"{_LEFT}(?P<title>\d{{1,2}})\s+UCS\s+(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})")

#: A statutory note is LAW, printed under a section rather than as one —
#: the LLSDC sourcebook "The Authority of Statutes Placed in Section Notes
#: of the United States Code" is the license — so "8 U.S.C. 1252 note" is a
#: real place distinct from 8 U.S.C. 1252, the same way an appendix is.
_USC_NOTE_TAIL = {
    prose: re.compile(prefix + r"notes?\b", re.IGNORECASE if prose else 0)
    for prose, prefix in (
        (False, r"\s+"),
        (True, r"(?:\s+|\s*,\s*)(?:(?P<position>preceding|following)\s+)?"),
    )
}

#: A code that names itself instead of its title number. The Internal Revenue
#: Code IS title 26, so "I.R.C. 337(d)" and "26 U.S.C. 337(d)" must reach one
#: identifier. The title comes from the expression that recognized the code —
#: never from a shared "guess the code" rule — and the three-letter
#: abbreviation publishes nothing without a section behind it, because naming
#: a code is not citing one. The section slot stays the bare
#: :data:`_USC_SECTION_SPAN`, matching :data:`_USC_STANDARD`'s own anchor:
#: "I.R.C. 1.6103" would truncate to section 1 of a code that is entirely
#: IRS regulations under this same title, and this pattern is read in the
#: SAME loop as the anchor and refused the SAME way — see
#: ``_usc_leading_section_is_untruncated``.
_INTERNAL_REVENUE_CODE = re.compile(
    rf"\bI\.?\s*R\.?\s*C\.?(?:\s*{_SECTION_MARKER})?\s*"
    rf"(?P<section>{_USC_SECTION_SPAN})",
    re.IGNORECASE,
)
#: The spellings that reach a U.S.C. title and section, with the title a
#: SELF-NAMING code supplies. A named code's title comes from the expression
#: that recognized the code — never from a shared "guess which code this is"
#: rule — which is why the number sits beside its own pattern here.
_USC_CODE_FORMS: tuple[tuple[re.Pattern[str], int | None], ...] = (
    (_USC_STANDARD, None),
    (_INTERNAL_REVENUE_CODE, 26),
)

#: OMB's own instrument series: "OMB Circular A-183", "OMB Bulletin No.
#: 93-11", "OMB Memorandum M-20-20". Bounded by the literal "OMB" and the
#: series shapes OMB itself uses (Circulars are A-NNN; memoranda M-YY-NN).
#: 408 residue rows cite these as legal authority. The office names itself two
#: ways — "OMB Circular A-25" and the longhand "Office of Management and
#: Budget Circular No. A-25" (21 rows, measured 2026-08-22) — one family, one
#: row shape.
_OMB_INSTRUMENT = re.compile(
    r"\b(?:OMB|Office\s+of\s+Management\s+and\s+Budget)\s+"
    r"(?P<kind>Circular|Bulletin|Memorandum|Memoranda)\s*"
    r"(?:No\.?\s*)?(?P<number>[AM]?-?\d{1,4}(?:-\d{1,4})?)"
)

# "Public Law", "Pub. L.", "Pub. Law", "P.L." — one law, four spellings.
# The separator tolerates a doubled dash: "PL 105\x96-261" is an en dash and
# a hyphen side by side, one separator typed twice (5 Agenda rows) — and a
# dash directly after the label: "PL-111-134" hyphenates the label to its
# number (13 rows, measured 2026-08-22).
# "Pub. L. No: 114-190" writes the No with a colon; both punctuation marks
# are the label's, not the number's.
# A zero pad is read through, not refused: "Pub. L. 111-05" is the American
# Recovery and Reinvestment Act, 111-5, and the pad was the whole reason the
# citation went unread -- 34 zero-padded numbers and 5 zero-padded
# Congresses in the parsing survey's Federal Register texts (2026-09-23).
# Both halves are read as integers, so the pad never reaches a key.
_PUBLIC_LAW = re.compile(
    rf"{_LEFT}(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)[\s-]*(?:no\.?:?\s*)?"
    rf"0*(?P<congress>[1-9]\d*)(?:\s*-\s*){{1,2}}0*(?P<number>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)

#: "Pub. L 103.311" — a dot in the separator slot. No Public Law citation
#: form is decimal, so a single dot between two in-shape integers directly
#: after the label is the dash's damage (16 Agenda rows, every one a real
#: law). The lookahead keeps dotted ranges out: "Pub. L. 205.600-205.607"
#: is CFR-shaped, reads as no Public Law, and stays refused.
_PUBLIC_LAW_DOT = re.compile(
    rf"{_LEFT}(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?"
    rf"(?P<congress>[1-9]\d{{1,2}})\.(?P<number>[1-9]\d{{0,2}})(?![.\-]?\d)",
    re.IGNORECASE,
)

# Capitalization is load-bearing where an abbreviation is also inside English
# words: the spelled forms may relax case, but bare "EO"/"E.O." must be
# uppercase or "Romeo 12345" mints an order. The spelled forms accept any
# order number (early orders are two digits); the bare form demands the
# modern 4-5 digit shape, because without a label the number is the only
# other evidence.
_EXECUTIVE_ORDER_SPELLED = re.compile(
    rf"{_LEFT}(?:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))\s*(?:Nos?\.?\s*)?(?P<number>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
#: "Executive Orders 13990 and 14008" — the plural licenses a number list,
#: the same rule the CFR and U.S.C. lists use.
_EXECUTIVE_ORDER_LIST_TAIL = re.compile(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?P<number>1?\d{4,5})\b")
#: The bare form tolerates two label damages, both measured 2026-08-22 and
#: both preserving the uppercase evidence: "EO." with its stray period
#: ("EO. 14221"), and "E0" with a zero where the O belongs ("E0 12250",
#: 9 rows) — a homoglyph reachable from "EO" by one keystroke and from no
#: other citation label. The abbreviated label also pluralises the way the
#: spelled one does — "E.O.s 12742 and 13603" (5 rows) — and the plural is
#: what licenses the number list, so refusing the "s" dropped an order.
_EXECUTIVE_ORDER_ABBREVIATED = re.compile(
    rf"{_LEFT}(?:EOs?\.?|E0|E\.\s*O\.?s?)\s*(?:No\.?s?\.?\s*)?(?P<number>\d{{4,5}}){_RIGHT}"
)

#: A Federal Register citation: "89 FR 91529". Uppercase "FR" only, for the
#: same reason bare "EO" is — lowercase "fr" is ordinary prose. The Bluebook
#: longhand "Fed. Reg." reads too ("86 Fed. Reg. 8267", measured
#: 2026-08-22), capitalized likewise. Volume bounded to the real series
#: (1..999); the page to the Register's actual widths. The separators
#: tolerate the publisher's own damage — "78FR 63152", "82-FR 22190" and
#: "83 FR32768" all occur in the Unified Agenda's timetable field — but
#: only one dash or nothing: "76 R 11462" (a lost F) and a CFR citation
#: sitting in the FR column stay unread rather than guessed.
#: The page may carry one thousands comma, the Bluebook's spelling ("88 Fed.
#: Reg. 12,345"): until 2026-09-23 the page stopped at the comma and this read
#: page 12. Only one comma followed by exactly three digits is a thousands
#: comma, so a list ("89 FR 91529, 91530" or "91529,91530") still reads its
#: first page whole, a comma page before a list comma or a sentence comma is
#: read ("88 Fed. Reg. 12,345, 12,350", "85 FR 43,304, the agency"), and a
#: number no page reaches ("1,234,567") reads as none.
_FR_CITATION_FORM = re.compile(
    # "Fed"/"FED" both read (the timetable builder uppercases its column
    # before parsing); the opening capitals stay required either way.
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,2}})\s*-?\s*(?:FR|F[Ee][Dd]\.?\s?R[Ee][Gg]\.?)\s*-?\s*"
    rf"(?P<page>\d{{1,3}},\d{{3}}(?!\d|,\d)|\d{{1,6}}(?!,\d{{3}}(?!\d))){_RIGHT}"
)

#: "Stat" must be capitalized for the same reason, and the digit ranges are
#: bounded to the real series (volume 1..~1400, page 1..99999). The label
#: tolerates the publisher's own damage, each spelling measured 2026-08-22:
#: lost separator spaces ("92 Stat.1660", "61Stat 1180" — the FR grammar's
#: fused-space lesson), the longhand "Statutes", and "Statue" — "61 Statue
#: 1180" (14 rows), one dropped letter from "Statute", reachable from no
#: other citation label. The page may be fused directly to an "as amended"
#: tail ("63 Stat 390as amended", 5 rows) — the words prove where the page
#: ends, so the boundary guard yields to them and only them.
#: A lettered Statutes volume: "70A Stat. 157". Volume 70A carries the 1956
#: enactment of Titles 10 and 32 into positive law (act of August 10, 1956,
#: ch. 1041, 70A Stat. 1), so the letter is part of the volume's name and not
#: damage. The integer grammar below cannot read these -- "70A" leaves an "A"
#: where it wants whitespace -- so no suppression is needed.
_STATUTE_LETTERED_VOLUME = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,2}}[A-Z])\s*Stat(?:utes?|ue)?\.{{0,2}}\s*"
    rf"(?P<page>[1-9]\d{{0,4}}){_RIGHT}"
)

_STATUTE_AT_LARGE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s*Stat(?:utes?|ue)?\.{{0,2}}\s*"
    rf"(?P<page>[1-9]\d{{0,4}})(?:{_RIGHT}|(?=as\s+amended\b))"
)

#: An appendix-paginated Statutes volume: "113 Stat. 1501A-293". Volumes
#: carrying incorporated appropriations acts (106-113, 106-554) page their
#: appendices "1501A-1", "2763A-326" — the page's identity is the lettered
#: compound, which the int32 page column cannot state without truncating or
#: minting, so it lives in its own text column. The separator between base
#: and leaf tolerates the comma the publisher writes ("114 Stat. 2763A, 326
#: to 328" — 32 rows; no Stat page is ever "2763A, 326" any other way), and
#: a range tail names the end leaf. Case-insensitive letter, uppercased on
#: capture: the Statutes print "2763A", one row types "2763a".
#:
#: The end leaf is CARRIED, and was not until 2026-08-22: the reader consumed
#: it and dropped it, because there is no second page column, and the only
#: trace was a "partial" status that says nothing about which endpoint went
#: missing. 23 distinct values, 181 source rows — every one of them Pub. L.
#: 106-554 sec. 1505 at 114 Stat. 2763A-326 to 2763A-328. It is carried as a
#: RANGE STRING in the same column, spelled with " to ", because a page's
#: identity here is already a string and a range of pages is not a page: a
#: consumer keying on one can tell the two apart by looking, which it could
#: not do if the endpoints were fused into a longer compound.
#: The end of a range names its leaf three ways, all of them in the corpus:
#: the full page again ("2763A-326 to 2763A-328"), the bare leaf ("to 328"),
#: or the leaf still wearing its separator ("to -328"). The full spelling is
#: tried FIRST and the leaf carries a right-hand boundary, because without
#: either one "to 2763A-328" reads its end leaf as "2763" — the first four
#: digits of the next page's own base — and publishes a range ending at a
#: page the string never named. Two guards for one hazard on purpose: the
#: alternative is the reading, the boundary is what refuses the misreading if
#: a later widening reorders the alternation.
_STATUTE_LETTERED_PAGE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s*Stat\.?\s*"
    r"(?P<base>[1-9]\d{0,3}[A-Za-z])\s*[-,]\s*-?(?P<leaf>\d{1,4})"
    r"(?:\s*(?:to|through|-)\s*"
    r"(?:(?P<end_base>[1-9]\d{0,3}[A-Za-z])\s*[-,]\s*)?-?(?P<leaf_end>\d{1,4})(?![0-9A-Za-z]))?"
)

#: What may follow a citation without making it partial: "et seq.",
#: "as amended", "and following", "ff.", and punctuation.
_IGNORABLE_TAIL = re.compile(
    r"^[\s,;:.]*(?:et\s+seq\.?|as\s+amended|and\s+following|ff\.?)?[\s,;:.]*$",
    re.IGNORECASE,
)

#: More characters outside :data:`_IGNORABLE_TAIL`'s punctuation class than
#: its longest phrase carries ("and following": twelve). A remainder holding
#: this many is partial whatever else it holds, and finding out costs only as
#: far as the thirteenth such character -- so a citation in a long document is
#: statused without copying the document around it. Written from the tail's
#: phrases, so it moves with them: ``test_the_status_bound_is_the_longest_tail``.
_MORE_THAN_AN_IGNORABLE_TAIL = re.compile(r"(?:[\s,;:.]*[^\s,;:.]){13}")

_USC_SECTION_ATOM = re.compile(r"(?P<number>\d+)(?P<suffix>[a-z]*)")


#: The words this module reads as citation STRUCTURE rather than as a scheme
#: label -- the markers, separators and tails its own patterns name. Each word
#: is paired with the pattern that names it and the phrase that proves the
#: pairing, so the census cannot drift from the grammar: a test walks this
#: table and asserts every pattern still matches its phrase.
#:
#: It exists for a reader OUTSIDE this module. A caller repairing a damaged
#: scheme label has to know whether the words left beside the token are
#: ordinary citation furniture ("et seq.", "note", "to") or something the
#: grammar has no rule for, and asking this table is the difference between a
#: fence and a hand-written stop-list.
_STRUCTURE_WORD_WITNESSES: Mapping[str, tuple[str, str]] = {
    "sec": (_SECTION_MARKER, "sec"),
    "secs": (_SECTION_MARKER, "secs"),
    "section": (_SECTION_MARKER, "section"),
    "sections": (_SECTION_MARKER, "sections"),
    "and": (_LIST_SEPARATOR, " and "),
    "to": (_RANGE_SEPARATOR, " to "),
    "through": (_RANGE_SEPARATOR, " through "),
    "thru": (_RANGE_SEPARATOR, " thru "),
    "et": (_IGNORABLE_TAIL.pattern, " et seq. "),
    "seq": (_IGNORABLE_TAIL.pattern, " et seq. "),
    "as": (_IGNORABLE_TAIL.pattern, " as amended "),
    "amended": (_IGNORABLE_TAIL.pattern, " as amended "),
    "following": (_IGNORABLE_TAIL.pattern, " and following "),
    "ff": (_IGNORABLE_TAIL.pattern, " ff. "),
    "note": (_USC_NOTE_TAIL[False].pattern, " note"),
    "notes": (_USC_NOTE_TAIL[False].pattern, " notes"),
}

#: The census itself, for a caller that only needs membership.
CITATION_STRUCTURE_WORDS: frozenset[str] = frozenset(_STRUCTURE_WORD_WITNESSES)


def names_citation_structure(word: object) -> bool:
    """Whether the grammar reads this word as citation structure.

    Case- and punctuation-insensitive, because the corpus writes "Sec.",
    "SEC" and "sec" for one marker. A word this answers False to is a word
    this module has no rule for, which is exactly what a repair fence needs
    to know.
    """

    return re.sub(r"[^a-z]", "", str(word or "").lower()) in CITATION_STRUCTURE_WORDS


#: The pinpoint a citation writes onto its section: "1651(b)(2)", "2704(a)(8)",
#: "1(4)". One or more parenthesised labels, GLUED to the section token — a
#: space before the parenthesis makes it something else, and "49 App. U.S.C. 1
#: to 85 (1988)" is the specimen that proves the rule earns its keep: that
#: "(1988)" is the edition the filer cited, not a subsection of §85.
#:
#: The label alphabet is :data:`~refspec.registry.usc_disposition_tables._GROUP`'s,
#: because the only reader of this is a query into that module's printed table
#: and a label it cannot spell is a label no printed row can match.
_USC_PINPOINT = re.compile(r"(?:\([0-9A-Za-z]{1,4}\))+")


def usc_section_pinpoint(text: object, section: object) -> str | None:
    """The subsection ``text`` states immediately after its ``section`` token.

    ``("49 USC 1651(b)(2)", "1651")`` -> ``"(b)(2)"``; ``None`` where the
    citation states no pinpoint on that token. The token is matched as
    :func:`_usc_section` already folded it, bounded on both sides, so the "1"
    of "1.51(F)" is not read as section 1 with a pinpoint — the fence class
    :data:`_DAMAGED_TOKEN` carries for the same reason.

    **A token inside a parenthesis is a LABEL and not a section**, which is
    why an opening bracket bounds the match on the left: without it the "(1)"
    of "49 U.S.C. App. 1(4), 3(1), 15(1)" reads as a second, bare occurrence
    of section 1 and refuses the pinpoint the citation plainly writes on it.

    **Two spellings refuse rather than pick.** "49 USC 1354(a) to 1354(c)"
    writes the same section twice with two different pinpoints, and a caller
    narrowing an answer by one of them would narrow by whichever came first.
    Returning ``None`` there leaves the unnarrowed answer standing, which is
    the wider and therefore the honest one.

    The parse does not carry this: ``usc_section`` drops subsection detail on
    purpose (see :func:`_usc_section`), and the tail stays UNCOVERED, which is
    why every pinpointed citation reads ``parse_status`` "partial". This
    function reads the same characters without moving either — a caller that
    needs the pinpoint asks for it, and the columns stay where they are.
    """

    token, body = str(section or "").strip().lower(), str(text or "")
    if not token:
        return None
    found = {
        match.group(1) or None
        for match in re.finditer(
            rf"(?<![0-9A-Za-z.\-(]){re.escape(token)}(?![0-9A-Za-z\-])({_USC_PINPOINT.pattern})?",
            body,
            re.IGNORECASE,
        )
    }
    return found.pop() if len(found) == 1 else None


#: What may sit between a chapter marker and a number it still governs: other
#: numbers, and the separators of a list. "49 USC 106(g), ch 447 and 451" is
#: the specimen — the "ch" is written once and governs both 447 AND 451 — and
#: a subsection pinpoint on an earlier member ("ch 447(a) and 451") does not
#: break the chain either. Anchored at the end, so the walk is a repeated
#: strip and never a search: the marker must be the last thing standing.
_CHAPTER_LIST_TAIL = re.compile(
    rf"(?:\d+[a-z]?(?:{_USC_PINPOINT.pattern})?)?\s*(?:[,;&]|\band\b|\bor\b|\s)+\s*$",
    re.IGNORECASE,
)
_CHAPTER_MARKER_AT_END = re.compile(rf"{_CHAPTER_MARKER}\s*$", re.IGNORECASE)


def usc_token_is_chapter_qualified(text: object, section: object) -> bool:
    """Whether a chapter marker earlier in the same list still governs ``section``.

    ``("49 USC 106(g), ch 447 and 451", "451")`` -> ``True``: one "ch" is
    written for both members, and the parse hands the second one to a caller
    as a bare section token. The visual review of 2026-08-23 (§ J, RIN
    2105-AD66) found that token routed into the pre-1994 Title 49 Appendix on
    its magnitude alone, and answered about a repealed 1930s block, while the
    filer's own abstract cites current subtitle VII.

    A FACT ABOUT THE TEXT, and nothing more. It does not say the token is a
    chapter: over the pinned build 40 rows in 11 distinct texts answer True,
    and 3 of those texts label SECTIONS "ch" ("49 U.S.C. 329 and chs. 41102,
    41301, 41708, 41709, and 41712"; "46 U.S.C. 70034, 70051, ch. 701 and
    70116") — real sections no chapter register holds. A caller that means to
    act on this must ask such a register too; see ``_judge_usc_sections``,
    whose guard does, and answers on 17 rows rather than 40.

    The walk is backwards from the token through list members and separators
    only, so a marker in an unrelated earlier clause cannot reach it: in "49
    USC ch 401, 411, and 417" the marker governs all three, and in "49 USC 329
    chs 401 and 417" it governs 401 and 417 but not the 329 in front of it.
    """

    token, body = str(section or "").strip().lower(), str(text or "")
    if not token:
        return False
    for match in re.finditer(rf"(?<![0-9A-Za-z.\-(]){re.escape(token)}(?![0-9A-Za-z\-])", body, re.IGNORECASE):
        head, previous = body[: match.start()], None
        while head != previous:
            head, previous = _CHAPTER_LIST_TAIL.sub("", head), head
        if _CHAPTER_MARKER_AT_END.search(head):
            return True
    return False


#: Values that state nothing: stringified nulls plus the Unified Agenda's own
#: placeholders ("Not Yet Determined" 5,338 times, "..." 6,873 times in the
#: authority field alone; "00 CFR NYD" in the CFR field). A consumer must be
#: able to tell "the publisher said nothing" from "the publisher said
#: something unreadable" — the same distinction the docket sentinels carry.
UNSTATED_SENTINELS = frozenset(
    {
        "",
        "none",
        "nan",
        "null",
        "n/a",
        "na",
        "...",
        "not yet determined",
        "undetermined",
        "not determined",
        "nyd",
        "tbd",
        "to be determined",
        "not applicable",
    }
)

#: Quotation marks around a placeholder are still a placeholder: the Agenda
#: writes '"Not Yet Determined"' with literal quotes 30 times.
_WRAPPING_QUOTES = re.compile(r"""^["'“”\s]+|["'“”\s]+$""")

#: A ZERO title and its scheme label, which the publisher's form glues in
#: front of a placeholder: "00 CFR NYD" (16 rows), "00 CFR None" (15),
#: "00 CFR 00" (3), "0 CFR 00" (1), "00 USC 00" (1) — 36 rows that were
#: reported as an impossible CFR title rather than as the placeholder they
#: are, while the 4,453 rows writing the bare "None" were read correctly.
#:
#: Only a zero title is looked past, and this is NOT the CFR-35 mistake in a
#: new coat: title 35 held the Panama Canal and a 1990s citation to it is
#: real, whereas no volume of either code has ever been numbered 0 in any
#: year. So the numeral cannot be a citation, and the only thing left for it
#: to be is the form's zero-fill.
_ZERO_TITLE_LABEL = re.compile(r"^0+\s*(?:C\.?\s?F\.?\s?R|U\.?\s?S\.?\s?C)\.?\s*", re.IGNORECASE)

#: What may follow that label and still state nothing, beyond the sentinels:
#: a part or section numbered zero, which locates nothing in either code.
#: This is the fence, and it earns its keep on exactly one row —
#: "0 CFR 150 to 189" (RIN 2070-AC97, ed 199510) is a TRUNCATED REAL
#: CITATION, corroborated by the same RIN and ordinal writing
#: "40 CFR 150 to 189" in ed 199604 and every edition after. It keeps its
#: impossible-title flag, which is that flag doing its job.
_ALL_ZEROS = re.compile(r"0+")


def states_nothing(text: object) -> bool:
    """Whether a field value is a placeholder rather than a statement."""

    value = _WRAPPING_QUOTES.sub("", str(text or ""))
    if value.casefold() in UNSTATED_SENTINELS:
        return True
    remainder, stripped = _ZERO_TITLE_LABEL.subn("", value, count=1)
    return bool(stripped) and (
        remainder.casefold() in UNSTATED_SENTINELS or _ALL_ZEROS.fullmatch(remainder) is not None
    )


# --------------------------------------------------------------------------- #
# Result types


@dataclass(frozen=True)
class CfrCitation:
    """One CFR reference, split and judged but never discarded."""

    cfr_title: int
    cfr_part: str | None
    cfr_section: str | None = None
    #: 1-50 and not Reserved. False keeps the row inspectable rather than
    #: dropping what a data-quality question needs.
    title_is_possible: bool = True
    #: False for a part whose digit run is longer than any real part — the
    #: publisher's lost-separator damage.
    part_is_plausible: bool | None = None


@dataclass(frozen=True)
class CfrCitationRange:
    """Two written endpoints, not one identifier or an expanded membership list."""

    start: CfrCitation
    end: CfrCitation


@dataclass(frozen=True)
class CfrCitationOccurrence:
    """A parsed CFR identity with its exact, codepoint-indexed source slice.

    List continuations inherit the title from ``context_start:context_end``.
    That span identifies the opening citation, or the complete group when its
    explicitly written title follows the coordinates (``of title N, Code ...``).
    A pinpoint records attached labels, not verified paragraph existence.
    Subparts and appendices retain their written container; list connectors
    remain in ``text``. A stated range records endpoints, never inferred members.
    """

    citation: CfrCitation | CfrCitationRange
    start: int
    end: int
    text: str
    pinpoint: tuple[str, ...] = ()
    context_start: int | None = None
    context_end: int | None = None
    subpart: str | None = None
    subpart_end: str | None = None
    appendix: str | None = None
    #: Multiple parts followed by subparts do not establish a pairing.
    qualifier_status: str | None = None
    range_end_pinpoint: tuple[str, ...] = ()
    refusal: str | None = None


@dataclass(frozen=True)
class AuthorityCitation:
    """One legal authority, with a status instead of silence.

    ``parse_status`` is "ok" when the citation covers its whole string apart
    from an ignorable tail ("et seq.", "as amended"), "partial" when prose or
    a declined range tail remains uncovered or the string carries several
    citations, and "failed" on the one ``other`` row an unreadable string
    still produces — nothing vanishes.
    """

    authority_type: str
    parse_status: str = "ok"
    usc_title: int | None = None
    usc_section: str | None = None
    usc_section_end: str | None = None
    #: How ``usc_section_end`` was arrived at — :data:`USC_SPAN_STATED` when
    #: the publisher wrote it, :data:`USC_SPAN_ABBREVIATED` when this module
    #: expanded it out of "2671-80". NULL where there is no span.
    #:
    #: A consumer that EXPANDS a span is making a claim about every section
    #: between the endpoints, and the two rules do not support that claim
    #: equally: 5 of the 68 abbreviated tokens in the pinned corpus expand to
    #: spans whose members are mostly not law — 16 U.S.C. 4601-31 claims 31
    #: sections of which 23 are not — while a stated span was read off the
    #: characters. Before this column the two were indistinguishable in the
    #: output. See :func:`_abbreviated_span`.
    usc_section_span_rule: str | None = None
    usc_chapter: str | None = None
    usc_chapter_end: str | None = None
    #: True when the section lives in the title's appendix, a different place
    #: from the title proper.
    usc_appendix: bool = False
    cfr_title: int | None = None
    cfr_part: str | None = None
    #: The section under the part, where the citation names one. "49 CFR 1.95"
    #: is one of 22 distinct DOT delegation sections under part 1, and without
    #: this they are one citation: :func:`parse_cfr_citations` has always read
    #: the section and this type had nowhere to put it, so every consumer of an
    #: authority row got "49 CFR part 1" for all 22 — 309 distinct values, 312
    #: citations, 4,126 authority rows over 90 (title, part) pairs.
    #:
    #: This said 4,186 while the test beside it said 4,126, which is what a
    #: number nothing recomputes does. 4,126 is the one that means what the
    #: sentence says: the authority ROWS that arrive one unit coarser, counted
    #: as each value's source rows times the CFR citations in it that name a
    #: section. (4,363 is a different question — every row of the table those
    #: 309 values produce, including the U.S.C. and Public Law rows from the
    #: same strings, which lose nothing.) Recomputed over the digest-pinned
    #: snapshot by
    #: :func:`test_the_cfr_section_population_is_one_number_recomputed`.
    cfr_section: str | None = None
    #: The CFR reader's own verdict on the part, carried rather than dropped.
    #: :func:`parse_cfr_citations` has always computed it and this type had no
    #: field, so the identical string was judged in the CFR reference table and
    #: unjudged in the authority table — "42 CFR 412106" is flagged there and
    #: was minted here with nothing said. NULL when there is no part to judge.
    #:
    #: It is a DIGIT-COUNT verdict and nothing more, which is what it says on
    #: :data:`_MAX_PLAUSIBLE_PART_DIGITS`: real parts reach five digits, so
    #: "49 CFR 30166" is plausible on this test and is still a U.S.C. section
    #: wearing a CFR label. See
    #: :func:`test_a_cfr_part_carries_its_verdict_and_the_retyping_stays_refused`
    #: for that population, and for what settling it would take.
    cfr_part_is_plausible: bool | None = None
    cfr_part_end: str | None = None
    cfr_section_end: str | None = None
    cfr_end_part_is_plausible: bool | None = None
    cfr_refusal: str | None = None
    reorganization_plan: str | None = None
    #: An act-relative authority ("Clean Air Act sec 112"): the OLRC popular
    #: name key, with the act's own section number when one was cited.
    #: Resolution to a U.S.C. identifier is act_resolution's job, not this
    #: type's — it carries what the text said and nothing it did not.
    act_key: str | None = None
    act_section: str | None = None
    #: A case-reporter citation: "123 F 3d 1460". Locates a decision.
    case_reporter: str | None = None
    case_volume: int | None = None
    case_page: int | None = None
    #: True when the citation names the statutory NOTE under a section — law
    #: printed below the section rather than as it, a different place the
    #: way an appendix is.
    usc_note: bool = False
    #: Presidential documents: proclamations are numbered; memoranda and
    #: notices are date-identified and carry a kind alone.
    presidential_doc_kind: str | None = None
    proclamation: str | None = None
    #: A department head's own instrument cited as authority.
    admin_order_kind: str | None = None
    admin_order_number: str | None = None
    #: Treaty series citations, Bluebook 21.4.5 order.
    treaty_series: str | None = None
    treaty_volume: int | None = None
    treaty_number: str | None = None
    treaty_page: int | None = None
    constitution_article: str | None = None
    constitution_section: str | None = None
    #: A Title 3 compilation locator used as authority: the page an EO was
    #: printed on, no identifier mintable.
    eo_compilation_start: str | None = None
    eo_compilation_page: str | None = None
    public_law: str | None = None
    executive_order: str | None = None
    statute_volume: int | None = None
    statute_page: int | None = None
    #: An appendix-paginated Statutes page: "2763A-326". The page's identity
    #: is the lettered compound, which the int page column cannot state
    #: without truncating or minting — so the int stays NULL and the
    #: identity lives here, uppercased ("2763a" is the same page).
    #:
    #: A RANGE of such pages is written "2763A-326 to 2763A-328" in this same
    #: column, spelled with " to " so a consumer keying on one page can see at
    #: a glance that this value is not one. There is no second page column and
    #: adding one the builder does not write would have carried the end leaf
    #: nowhere; dropping it silently is what this replaced.
    statute_page_text: str | None = None
    #: Whether this volume can carry a law of the Public Law cited BESIDE it.
    #: NULL unless the value states exactly one Public Law textually adjacent
    #: to this Statutes cite, and NULL where the Congress is outside the
    #: numbered series (``pl_congress_in_series`` reports that one). A verdict,
    #: never a correction: see
    #: :func:`test_a_statutes_volume_is_fenced_by_the_public_law_beside_it` for
    #: why the relation cannot pick which of the two readings is damaged.
    statute_volume_matches_public_law: bool | None = None
    #: The volume as printed when it carries a letter ("70A"), with
    #: ``statute_volume`` left NULL: a lettered volume is not the integer
    #: volume beside it, and 70A Stat. is not 70 Stat.
    statute_volume_text: str | None = None
    #: What an unresolvable value states about itself. Populated only on rows
    #: nothing could read; a resolved row carries act_key instead.
    stated_act_name: str | None = None
    stated_section: str | None = None
    #: A Federal Register citation in the authority column — a document
    #: locator in the wrong field, typed like the CFR family (101 distinct
    #: unreadable values carried one, measured 2026-08-21).
    fr_volume: int | None = None
    fr_page: int | None = None
    #: A Revised Statutes section: "R.S. 463". A different namespace from
    #: every U.S.C. title, never merged with one.
    revised_statute_section: str | None = None
    #: A D.C. Code section in title-section form ("24-131"); the older
    #: title-first spelling ("26 DC Code 102") reads to the same compound.
    #: None when the value names the Code without a readable section.
    dc_code_section: str | None = None
    #: True when :data:`_USC_LIST_TAIL` reached this member by scanning PAST
    #: a Statutes-at-Large citation ("12 U.S.C. 1701 et seq.; 101 Stat. 1568,
    #: 1608" -- the second number is the SAME Public Law's own pinpoint page,
    #: not a resumed section of title 12, and this module has no way to tell
    #: the two apart by shape alone: "sec. 412, 126 Stat. 89, 44101,
    #: 44701-44702, ..." (14 CFR 121's own authority note) is the identical
    #: shape and genuinely DOES resume a real U.S.C. list. A LEXICAL FACT,
    #: not a verdict — this module is deliberately oracle-free (the
    #: section-existence oracle imports it, so the reverse is circular; see
    #: the U.S.C. section-token doctrine above). A consumer that can reach the
    #: oracle (or another witness) gates admission on it; one that cannot
    #: should treat this exactly as ambiguous as it is. See
    #: :func:`refspec.registry.cfr_authority_notes.read_note_citations` for
    #: the note-side gate. Never True for the citation that is ITSELF the
    #: Statutes-at-Large family, only for a U.S.C. list member reached after
    #: one.
    usc_section_after_statute: bool = False


@dataclass(frozen=True)
class EoCompilationLocator:
    """A Title 3 compilation locator for a presidential document.

    Deliberately carries no identifier — the volume and page locate a printed
    document (including a proclamation), and inventing a CFR citation or order number
    would be one of the two wrong answers this type exists to refuse.
    """

    compilation_start: str
    compilation_end: str | None
    page: str | None
    page_end: str | None = None


@dataclass(frozen=True)
class EoCompilationOccurrence:
    """A compilation locator and its exact original source coordinates."""

    locator: EoCompilationLocator
    start: int
    end: int
    text: str
    refusal: str | None = None


# --------------------------------------------------------------------------- #
# Helpers


def _cfr_title_is_possible(title: int) -> bool:
    # 1-50, title 35 included: Reserved today, Panama Canal until 2000, and a
    # grammar that judged by today's roster called 115 real 1990s citations
    # impossible before this was web-verified. Named for its code because
    # ``usc_title_is_possible`` is a DIFFERENT rule over a different series,
    # and a bare ``_title_is_possible`` beside it invited reading one as the
    # private half of the other.
    return 1 <= title <= CFR_TITLE_COUNT


def _part_is_plausible(part: str | None) -> bool | None:
    if part is None:
        return None
    # A hyphen separates components, not a lost decimal: 102-193 is a
    # publisher-defined part, while the single digit run 412106 is suspect.
    return all(sum(c.isdigit() for c in atom) <= _MAX_PLAUSIBLE_PART_DIGITS for atom in part.split("-"))


def _canonical_part(part: str | None) -> str | None:
    """Strip leading zeros and a wrapped hyphen's space: the part is a JOIN KEY, and "0718" must meet "718"."""

    if part is None:
        return None
    head, separator, tail = re.sub(r"-[ \t]+", "-", part).partition("-")
    return (head.lstrip("0") or "0") + separator + tail


def _normalize_dashes(text: str) -> str:
    """:data:`_DASHES` applied: every dash spelling to "-", one character for one.

    Written as one ``str.replace`` per spelling rather than ``translate``,
    which gives the same string about sixty times faster (the whole text is
    folded several times per reading, and a budget volume is twelve million
    characters); ``test_dash_folding_is_the_translation_table`` holds the two
    equal.
    """
    for dash in DASH_SPELLINGS:
        text = text.replace(dash, "-")
    return text


#: A zero PAD in front of a section number, which the section does not own.
#: The Agenda's filers pad the way the CFR title field does — RIN 1545-BL12
#: writes "26 USC 0987" and "26 USC 0989(c)" for the §987/§989 foreign-currency
#: pair, beside an unpadded "26 USC 7805" — and the pad went straight into the
#: identity column, where it breaks every join: 943 rows / 101 distinct values
#: / 48 (title, section) pairs, 941 of the rows in title 26, measured
#: 2026-08-22 over the pinned Agenda table.
#:
#: **No U.S.C. section is legitimately zero-padded**, and that is measured, not
#: assumed: zero of the 59,364 sections in the OLRC current release point and
#: zero of the 1,572,225 annual-edition section rows (67,022 distinct) begin
#: with a "0", and neither do any of the 1,751 + 49,960 printed range
#: endpoints (``research/evidence/usc-section-oracle-2026-08-24/``, the
#: generation-2 oracle; re-measured 2026-08-31 after the twelve uppercase
#: volumes were recovered -- the distinct count did not move). All 48
#: padded pairs the corpus states resolve to a pair the oracle HAS seen once
#: the pad is stripped, and none of them is real as written. So this is the
#: :func:`_canonical_part` rule one column over — the section is a JOIN KEY,
#: and "0989" must meet "989" — and the stated text is untouched, because the
#: table carries ``authority_text`` beside the identity.
#:
#: The pad is stripped only where DIGITS remain behind it, so "00" reads as
#: section 0 rather than as nothing, and "1002" keeps its own zero.
#:
#: NAMED REFUSAL, and it is why the pad after a hyphen is read only when the
#: stem ends in a LETTER. "15 USC 80a-06(c)" can only be 15 U.S.C. 80a-6
#: (Investment Company Act §6; 1 value, 20 rows) because an abbreviated span
#: drops a stem's repeated leading DIGITS and "80a" ends in none — exactly one
#: survivor. Where the stem does end in a digit both readings are open:
#: "49 USC 20701-03" is §§20701-20703 abbreviated, NOT a padded §20701-3, and
#: 15 further values / 33 rows in title 49 and title 38 read the same way.
#: Those belong to the span rule, which decides them by their own evidence;
#: stripping their pad here would hide them from it.
_ZERO_PADDED_SECTION = re.compile(r"(?:^|(?<=[a-z]-))0+(?=\d)")


def _usc_section(value: str | None) -> str | None:
    """Fold a section token as the tables fold theirs, drop subsection detail, close a lost space, strip a zero pad.

    The fold is ``schemas.tables.usc_section_key`` -- trimmed, lower-cased,
    every dash spelling a hyphen -- so the key a citation publishes and the
    ``usc_section_key`` column of ``law_code_sections`` and ``table3_records``
    are folded by one function (decision 30).
    """

    if value is None:
        return None
    text = re.sub(r"-[ \t]+", "-", re.sub(r"\([^)]*\)", "", usc_section_key(value)))
    return _ZERO_PADDED_SECTION.sub("", text) or None


def _usc_section_order(section: str | None) -> tuple[int, str, int] | None:
    """Order a U.S.C. section by numeric stem, letter suffix, then compound leaf.

    ``7671`` < ``7671a`` < ``7671q`` < ``7672``. None for anything that is not
    a well-formed token, so a caller can never compare two values it does not
    understand.

    The third component is the COMPOUND LEAF, and it is what lets "460k" sort
    before "460k-4". The Code numbers a run of inserted sections that way --
    16 U.S.C. 460k, 460k-1, 460k-2, 460k-3, 460k-4, the Refuge Recreation Act
    -- so a range whose endpoint is compound cannot be ordered without it, and
    an endpoint that cannot be ordered is an endpoint that gets dropped. A
    token with no leaf sorts as leaf 0, which is exactly where the Code puts
    it. Every key was a 2-tuple before 2026-08-24 and the widening is inert on
    its own: :func:`_usc_section_range` splits a one-token pair on the hyphen
    BEFORE it asks for a key, so the only comparison this changes is one where
    a compound token arrives whole -- which is a spelled range's endpoint, and
    the pattern could not capture one until this same unit widened it.
    """

    if not section:
        return None
    stem, _, leaf = section.partition("-")
    match = _USC_SECTION_ATOM.fullmatch(stem)
    if match is None or (leaf and not leaf.isdigit()):
        return None
    return (int(match["number"]), match["suffix"], int(leaf) if leaf else 0)


#: The largest gap an abbreviated span may cross, in sections. Bluebook 3.2(a)
#: and the GPO Style Manual both abbreviate by dropping a second endpoint's
#: REPEATED LEADING DIGITS and keeping the last two, so the endpoints agree on
#: everything above the retained pair and the span cannot reach 100. It is
#: written as a bound rather than derived from the leaf's length because a
#: three-digit leaf ("1804-805") is the same abbreviation with one more digit
#: kept, and there the length alone permits a span of 999.
_ABBREVIATED_SPAN_MAX_GAP = 99
_ABBREVIATED_SPAN_MIN_LEAF_DIGITS = 2


def _abbreviated_span(section: str) -> tuple[str, str] | None:
    """The two endpoints an abbreviated span states, or None if it states none.

    "2671-80" is §§2671-2680, not a section named "2671-80": GPO and Bluebook
    3.2(a) abbreviate an inclusive span by dropping the repeated leading digits
    of its second endpoint. The grammar kept the whole token — a documented
    fail-closed choice — but the token then landed in the section IDENTITY
    column, indistinguishable from a real compound name like "1395w-4", and 264
    rows over 68 distinct (title, token) pairs were published that way
    (measured 2026-08-22 over the pinned Agenda table).

    What buys the reading is the oracle, not the shape. Of those 68 tokens,
    **zero name a real section as written**, and **62 expand to a span whose
    BOTH endpoints are real** — 246 of the 264 rows — against the pinned OLRC
    oracle in ``research/evidence/usc-section-oracle-2026-08-24``. So the
    column carries 264 rows of a name that is not law, and the span it becomes
    is law at both ends in 62 of 68.

    (This paragraph said 63 and 249 until the population was recounted rather
    than restated: "42 USC 105-33" was missing from the list of misses below.
    A number in prose with no check behind it drifts, so
    :func:`test_the_phantom_spans_are_recounted_not_restated` now recomputes
    every figure in this docstring from the pinned corpus and the oracle.)

    **The other six are PHANTOM SPANS, and the expansion is not law**: a
    consumer that walks a span's members gets a claim over every section
    between the endpoints, and for these the claim is mostly false — 16 U.S.C.
    4601-31 (really 460l-31, a lowercase L read as a one) covers 31 sections of
    which 8 are real, 16 U.S.C. 4602-31 7 of 30, 42 U.S.C. 105-33 6 of 29,
    26 U.S.C. 1502-13 4 of 12, 42 U.S.C. 3007-11 1 of 5, and 8 U.S.C.
    81611-1613 (the title glued to its own sections) 0 of 3. They are no worse
    off as a span than as a token naming nothing, and they are not repaired
    here.

    An ENDPOINT test would not be the whole answer even where one is available:
    16 U.S.C. 1801-81 and 42 U.S.C. 12101-13 pass both endpoints and are still
    sparse inside — Magnuson-Stevens alone claims 81 sections of which 36 are
    law, a bigger miss than any of the six. Counting members rather than
    endpoints, 60 of the 68 tokens claim nothing but law.

    What they are is SAID, in two columns that were silent. Every expansion
    carries :data:`USC_SPAN_ABBREVIATED` in ``usc_section_span_rule``, so an
    expanded span is distinguishable from a stated one; and no expansion is
    ever typed "ok", so a consumer filtering on status never walks one by
    accident. Both are blunter than the right answer, which is to ask an oracle
    whether the endpoints are law — and that answer is out of this module's
    reach by layering, not by expense: ``usc_section_oracle`` imports this
    module, so this module cannot import it, and the oracle's own tables are a
    pinned evidence directory rather than something a pure text function reads.
    A reader that HOLDS an oracle should re-type these five there.

    Three guards, each measured:

    * The leaf needs TWO digits. Without that the predicate flags the real
      sections 42 U.S.C. 288-1…288-6, 7 U.S.C. 1358-1 and 26 U.S.C. 460-6 —
      251 of the 282 real hyphenated all-digit sections have a one-digit leaf,
      and every one of them would be read as a span.
    * The leaf must be SHORTER than the stem, so a pair that repeats nothing
      ("4801-4582", "7671-7671") is not an abbreviation of anything.
    * The expansion must ASCEND and stay inside
      :data:`_ABBREVIATED_SPAN_MAX_GAP`. Ascending alone leaves
      "201701-20702" reading as a 19,001-section span.

    STATED HAZARD, and it is the reason the fail-closed line above was true
    when it was written: six real sections survive all three guards —
    42 U.S.C. 5714-21, 5714-22, 5714-23, 5714-24, 5714-25 and 5714-41, whose
    compound leaves happen to ascend within 99 of their stem. Nothing in the
    characters tells them from "2671-80", and this module holds no
    section-existence oracle to ask. They are measured INERT on this corpus:
    zero of the 42,642 distinct authority values name any of the six. A reader
    who acquires a section oracle should fence them there rather than here.
    """

    stem, _, leaf = section.partition("-")
    if not (stem.isdigit() and leaf.isdigit()):
        return None
    if not _ABBREVIATED_SPAN_MIN_LEAF_DIGITS <= len(leaf) < len(stem):
        return None
    end = f"{stem[: -len(leaf)]}{leaf}"
    if not 0 < int(end) - int(stem) <= _ABBREVIATED_SPAN_MAX_GAP:
        return None
    return (stem, end)


#: How the second endpoint of a section span was arrived at. The publisher
#: WROTE it ("7401 to 7671q", "7401-7671q" resolved by the ordering rule), or
#: this module EXPANDED it out of an abbreviation ("2671-80" → §§2671-2680).
#: One is a reading of the characters and the other is an inference about
#: them, they land in the same two columns, and before these names nothing
#: told them apart. See :func:`_abbreviated_span` for what the inference costs.
USC_SPAN_STATED = "stated"
USC_SPAN_ABBREVIATED = "abbreviated-span"


def _usc_section_range(section: str | None, range_end: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Split a section token into ``(section, range_end, span_rule)``.

    A hyphen means two things in the U.S. Code: in "1395w-4" and "300j-9" it
    is part of one section's name; in "7401-7671q" it separates a range's
    endpoints. Nothing in the characters distinguishes them, so the ordering
    does: a range is a pair whose second endpoint sorts strictly after its
    first, and a compound name never satisfies that because its suffix is a
    small ordinal.

    A pair the ordering rule declines gets one further question: is it an
    ABBREVIATED span? See :func:`_abbreviated_span` for the three guards and
    the oracle that bought them. Everything the ordering rule and the
    abbreviation rule both decline — "4801-4582", "7671-7671", "80a-06" —
    keeps the original token whole, because reading it either way would still
    be an invention.

    THE SECOND QUESTION IS ASKED OF A SPELLED PAIR TOO, and it was not until
    2026-08-24. The rule said "a spelled range states its own endpoints, so
    there is nothing abbreviated to expand" — which is true of the SPELLING
    and false of the corpus: a publisher who writes "12 USC 1817 to 19" has
    abbreviated exactly as one who writes "1817-19" has, and the module read
    the second and dropped the first. 54 values / 149 rows stated a range that
    way and published no end at all. The two spellings now give the identical
    answer, which is the only defensible pair of readings for them, and the
    abbreviation's own three guards do the refusing: a one-digit leaf, a leaf
    no shorter than its stem, and a gap over 99 are refused whichever
    separator the publisher used, so "5 USC 706 to 6" stays a single section.

    The third return value names WHICH of the two answered, because they are
    not equally strong and the columns cannot say so by themselves.
    """

    if not section:
        return (section, None, None)
    if range_end is not None:
        start, end = section, range_end
    elif section.count("-") == 1:
        start, end = section.split("-")
    else:
        return (section, None, None)
    low, high = _usc_section_order(start), _usc_section_order(end)
    if low is not None and high is not None and low < high:
        return (start, end, USC_SPAN_STATED)
    expanded = _abbreviated_span(section if range_end is None else f"{start}-{end}")
    return (*expanded, USC_SPAN_ABBREVIATED) if expanded else (section, None, None)


def _usc_section_fields(section: str | None, range_end: str | None = None) -> dict[str, str | None]:
    """The three section columns a U.S.C. citation states.

    The subsection strip and the ordering rule always travel together — five
    readers apply both, and none of them may apply only one — so they are
    composed here and the columns are named once. Returned as fields rather
    than as a pair because the pair's two halves are easy to swap silently.
    """

    start, end, rule = _usc_section_range(_usc_section(section), _usc_section(range_end))
    return {"usc_section": start, "usc_section_end": end, "usc_section_span_rule": rule}


#: How far above a title's attested 99th percentile a section may sit before
#: the magnitude alone says it cannot belong to that title. Ten, and the
#: number is bought rather than chosen: at ten, ZERO of the 66,780 real
#: (title, section) pairs in the pinned OLRC oracle sits above its title's
#: ceiling when the ceiling is derived over distinct citations, and exactly
#: ONE does when it is derived over rows — 47 U.S.C. 11007, the Broadband
#: DATA Act of 2020, which this corpus never cites.
_SECTION_MAGNITUDE_HEADROOM = 10


def _percentile(values: list[int], fraction: float) -> float:
    """Linear-interpolated percentile, so a title with few sections still has one."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def usc_section_ceilings(citations: Iterable[tuple[int | None, str | None, int]]) -> dict[int, float]:
    """A per-title section ceiling, derived from a corpus that cites the Code.

    Each item is (title, section, how many rows say it). The ceiling is the
    99th percentile of the section's numeric stem, times
    :data:`_SECTION_MAGNITUDE_HEADROOM`.

    A HEURISTIC, and named one: it is the corpus judging itself, with no
    oracle anywhere. It exists because ``usc_title_is_possible`` fences the
    title and NOTHING fences the section, and because it costs one pass over
    an artifact a consumer already has — cheap enough to run in CI, which the
    real section-existence oracle is not.

    Its two weaknesses are both consequences of that: the damaged values help
    set the ceiling that is supposed to catch them (with the pinned Agenda
    table, 33 U.S.C. 70116 and 70034 are themselves inside title 33's top one
    percent of DISTINCT citations, so weighting by rows is what exposes them),
    and a title the corpus cites thinly gets a ceiling from thin evidence.
    """

    stems: dict[int, list[int]] = {}
    for title, section, weight in citations:
        stem = None if section is None else _USC_SECTION_ATOM.match(section)
        if title is None or stem is None:
            continue
        stems.setdefault(title, []).extend([int(stem["number"])] * weight)
    return {title: _percentile(values, 0.99) * _SECTION_MAGNITUDE_HEADROOM for title, values in stems.items()}


def usc_section_magnitude_is_plausible(
    title: int | None, section: str | None, ceilings: Mapping[int, float]
) -> bool | None:
    """Whether a section's magnitude is possible for its title, per ``ceilings``.

    None where there is nothing to judge — no title, no readable section, or a
    title the corpus never cited, which is a silence and not a verdict. A
    LABEL and never a repair: a false verdict here costs a flag, not a
    citation, which is the only posture a heuristic may take.
    """

    stem = None if section is None else _USC_SECTION_ATOM.match(section)
    ceiling = None if title is None else ceilings.get(title)
    if stem is None or ceiling is None:
        return None
    return int(stem["number"]) <= ceiling


def _statute_lettered_page(match: re.Match[str]) -> tuple[str, int]:
    """What a lettered Statutes page states, and the offset it accounts for.

    One page ("2763A-326") or a range of them ("2763A-326 to 2763A-328"), and
    the two answers travel together: the page text and the coverage end are
    the same decision seen twice, and computing them apart is how the end
    leaf came to be consumed without being carried.

    The ordering rule is the U.S.C. one, for the same reason — an end leaf
    that does not follow its start is not a range, and reading it either way
    would be an invention. A range whose end names a DIFFERENT base is
    declined on the same terms: "1501A" and "2763A" are appendices of
    different acts, and a span across them is not a span. A declined tail
    stays uncovered, so the row is partial and the characters remain visible.
    """

    base, leaf = match.group("base").upper(), match.group("leaf")
    end, end_base = match.group("leaf_end"), match.group("end_base")
    declined = end is None or int(end) <= int(leaf) or (end_base is not None and end_base.upper() != base)
    if declined:
        return f"{base}-{leaf}", match.end("leaf")
    return f"{base}-{leaf} to {base}-{end}", match.end("leaf_end")


#: Both Public Law spellings, in the order the field reader reads them.
_PUBLIC_LAW_FORMS: tuple[re.Pattern[str], ...] = (_PUBLIC_LAW, _PUBLIC_LAW_DOT)


def _public_law_fields(match: re.Match[str]) -> dict[str, Any]:
    """A Public Law match as the row it states: congress and number, each read as an integer."""

    return {
        "authority_type": "public_law",
        "public_law": f"{int(match.group('congress'))}-{int(match.group('number'))}",
    }


type _VolumeVerdict = Callable[[re.Match[str]], bool | None]


def _lettered_page_statute(match: re.Match[str], verdict: _VolumeVerdict) -> dict[str, Any]:
    return {
        "authority_type": "statute_at_large",
        "statute_volume": int(match.group("volume")),
        "statute_page_text": _statute_lettered_page(match)[0],
        "statute_volume_matches_public_law": verdict(match),
    }


def _lettered_volume_statute(match: re.Match[str], _verdict: _VolumeVerdict) -> dict[str, Any]:
    return {
        "authority_type": "statute_at_large",
        "statute_volume_text": match.group("volume").upper(),
        "statute_page": int(match.group("page")),
    }


def _integer_statute(match: re.Match[str], verdict: _VolumeVerdict) -> dict[str, Any]:
    return {
        "authority_type": "statute_at_large",
        "statute_volume": int(match.group("volume")),
        "statute_page": int(match.group("page")),
        "statute_volume_matches_public_law": verdict(match),
    }


#: The three Statutes families as ``(pattern, row fields, covered end)``, in
#: the order they are read. Lettered pages are read before the integer
#: grammar, which cannot reach them at all ("2763A" fails its boundary guard)
#: — so the order is for the reader, not for correctness. A range tail's end
#: leaf is carried in the page text and therefore covered; a tail the ordering
#: rule declines is consumed, uncarried and uncovered, which keeps that row
#: partial. Written once so the field reader and :func:`find_statute_citations`
#: cannot read a family two ways.
_STATUTE_FAMILIES: tuple[
    tuple[
        re.Pattern[str],
        Callable[[re.Match[str], _VolumeVerdict], dict[str, Any]],
        Callable[[re.Match[str]], int] | None,
    ],
    ...,
] = (
    (_STATUTE_LETTERED_PAGE, _lettered_page_statute, lambda match: _statute_lettered_page(match)[1]),
    (_STATUTE_LETTERED_VOLUME, _lettered_volume_statute, None),
    (_STATUTE_AT_LARGE, _integer_statute, None),
)


#: What may stand between a Public Law and the Statutes cite that belongs to
#: it: punctuation, and the law's own approval date. Nothing else — a WORD
#: between them is another citation's, and it is what separates "PL 92-500 76
#: Stat. 816" (one law, two spellings, and they disagree) from "act A at Stat
#: X **as amended by** act B" (two laws, and pairing them proves nothing).
#: The date is admitted because the publisher writes it inside the citation:
#: "Pub. L. 98-192, Dec. 15, 1971, 85 Stat. 646" is one citation whose own
#: date settles which half is damaged.
#:
#: Measured over the pinned table 2026-08-22: 793 distinct values state
#: exactly one Public Law and exactly one Statutes cite (8,430 rows), and 658
#: of them / 7,421 rows are adjacent in this sense. The 135 that are not are
#: the "as amended" shape the adjacency rule exists to drop.
_PUBLIC_LAW_TO_STATUTE = re.compile(rf"[\s,;:()\[\]]*(?:(?:{_SPELLED_DATE.pattern})[\s,;:()\[\]]*)?", re.IGNORECASE)


class _PublicLawsBeside:
    """The Public Laws of one text, ordered by where they end, to ask which one stands before a Statutes cite.

    Only a law ending at or before the cite can stand beside it, and the walk
    back from the nearest such law stops at the first whose gap already holds
    another whole Public Law: a gap :data:`_PUBLIC_LAW_TO_STATUTE` accepts is
    punctuation and one spelled date, and a law's opening ``P`` -- never
    preceded by a letter -- can be neither, so no law further back can stand
    beside the cite either. The gap is matched in place (``pos``/``endpos``),
    never sliced out, so judging every cite of a long text costs its laws
    once, not once per cite.
    """

    def __init__(self, text: str, public_laws: Iterable[re.Match[str]]) -> None:
        self.text = text
        self.laws = sorted(public_laws, key=lambda match: match.end())
        self.ends = [match.end() for match in self.laws]

    def congress(self, statute: re.Match[str]) -> int | None:
        beside: list[re.Match[str]] = []
        latest_start = -1
        for index in range(bisect_right(self.ends, statute.start()) - 1, -1, -1):
            law = self.laws[index]
            if law.end() <= latest_start:
                break
            if _PUBLIC_LAW_TO_STATUTE.fullmatch(self.text, law.end(), statute.start()):
                beside.append(law)
            latest_start = max(latest_start, law.start())
        return int(beside[0].group("congress")) if len(beside) == 1 else None


def _congress_beside(text: str, public_laws: list[re.Match[str]], statute: re.Match[str]) -> int | None:
    """The Congress of the one Public Law standing next to this Statutes cite.

    None where none stands next to it, and None where SEVERAL do — a fence
    that cannot say which law the volume belongs to has nothing to judge.
    One cite at a time; a reader judging many builds :class:`_PublicLawsBeside`
    once instead.
    """

    return _PublicLawsBeside(text, public_laws).congress(statute)


def _statutes_volume_verdict(normalized: str, public_laws: list[re.Match[str]]) -> _VolumeVerdict:
    """Judge a Statutes volume against the one Public Law standing beside it in ``normalized``.

    ``public_laws`` may still be filling when this is built -- the field reader
    reads the laws before the Statutes -- so the index is taken on first use.
    """
    index: list[_PublicLawsBeside] = []

    def verdict(match: re.Match[str]) -> bool | None:
        if not index:
            index.append(_PublicLawsBeside(normalized, public_laws))
        return statutes_volume_matches_congress(index[0].congress(match), int(match.group("volume")))

    return verdict


def _spans_owning_their_comma(text: str) -> tuple[tuple[int, int], ...]:
    """Where a comma in ``text`` belongs to a date or an act name, not a list."""

    return tuple(match.span() for pattern in _COMMAS_THAT_BELONG_TO_A_NAME for match in pattern.finditer(text))


def _lies_inside(spans: tuple[tuple[int, int], ...], start: int, end: int) -> bool:
    return any(low <= start and end <= high for low, high in spans)


def _containment(spans: Iterable[tuple[int, int]]) -> Callable[[int, int], bool]:
    """:func:`_lies_inside` over fixed spans, answered by bisect rather than by a scan.

    The spans are ordered by where they open, each paired with the furthest
    any span opening no later reaches, so "some span holds ``start..end``" is
    one lookup: ``O(log n)`` a question, where a scan per list member made the
    list walk quadratic in a long document.
    """

    ordered = sorted(spans)
    opens = [low for low, _ in ordered]
    reach = list(accumulate((high for _, high in ordered), max))

    def holds(start: int, end: int) -> bool:
        index = bisect_right(opens, start)
        return index > 0 and reach[index - 1] >= end

    return holds


def _status_for_span(text: str, start: int, end: int) -> str:
    """Status for a citation covering ``text[start:end]`` and nothing else.

    The span is passed rather than taken from a match, because a U.S.C. match
    may consume a range tail the ordering rule then declines — the declined
    characters are not covered and must still count against "ok".
    """

    if _MORE_THAN_AN_IGNORABLE_TAIL.match(text, 0, start) or _MORE_THAN_AN_IGNORABLE_TAIL.match(text, end):
        return "partial"
    remainder = f"{text[:start]} {text[end:]}"
    return "ok" if _IGNORABLE_TAIL.fullmatch(remainder) else "partial"


#: :data:`_DOT_TRUNCATION_SIGNATURE` compiled as a POSITIVE match, where
#: :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` is the same string as a refusal.
#: Both derive from that one constant so a change to what truncation LOOKS
#: like cannot reach one reader and miss the other. Used where a citation's
#: own match must still stand — to seed :data:`_USC_LIST_TAIL`'s walk — but
#: the section it carries must not be minted from a truncated read.
_DOT_TRUNCATES_A_SECTION = re.compile(_DOT_TRUNCATION_SIGNATURE)


def _usc_leading_section_is_untruncated(text: str, match: re.Match[str]) -> bool:
    """Whether ``match``'s bare ``section`` group is a real section.

    False only for a BARE token — a hyphenated span is a range or a compound
    name and :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION` never guards it,
    whatever reads it — immediately followed by ".<digits>" that is not
    itself the lead of an explicit CFR citation: the reg-shaped truncation
    :data:`_USC_STANDARD` and :data:`_INTERNAL_REVENUE_CODE` both anchor on
    ("26 USC 1.104-1(c)" truncates to section "1", a real but wrong section;
    155 rows / 31 RINs measured in research/evidence/reg-dot-fence-2026-09-01/).

    ``match`` itself is used regardless of what this returns — a list-tail
    walk seeded from it must still run — only the row this match would
    otherwise produce is withheld.
    """

    section = match.group("section")
    if section is None or "-" in section:
        return True
    return _DOT_TRUNCATES_A_SECTION.match(text, match.end("section")) is None


# --------------------------------------------------------------------------- #
# CFR parsing


def parse_eo_compilation_locators(text: str) -> tuple[EoCompilationLocator, ...]:
    """Read every Title 3 compilation locator, identifying nothing."""

    return tuple(item.locator for item in find_eo_compilation_locators(text))


def find_eo_compilation_locators(text: str) -> tuple[EoCompilationOccurrence, ...]:
    """Read volume/page coordinates without inferring an order or CFR identity.

    Repetitions and spelling survive. An unclosed page-first parenthetical
    retains its observed fields with a refusal; it must not become a CFR part.
    This reader requires contiguous source text, not a layout reconstruction.
    """
    normalized = _normalize_dashes(text)
    return tuple(
        EoCompilationOccurrence(
            locator=EoCompilationLocator(
                compilation_start=match.group("start"),
                compilation_end=_compilation_end(match),
                page=match.group("page_before") or match.group("page"),
                page_end=match.group("page_before_end") or match.group("page_end"),
            ),
            start=match.start(),
            end=match.end(),
            text=text[match.start() : match.end()],
            refusal=(
                "compilation_parenthetical_unclosed"
                if match.group("page_before") is not None and match.group("closing") is None
                else None
            ),
        )
        for match in _EO_COMPILATION.finditer(normalized)
    )


def _excise_compilations(text: str) -> str:
    """Blank out compilation locators so the CFR grammar cannot read them.

    "3 CFR, 1977 Comp., p. 123" is not a CFR citation, and left in place it
    parses as title 3, part 1977 — plausible on every axis and entirely
    fabricated. Spans are replaced with spaces so every other citation keeps
    its offsets.
    """

    def _blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    return _EO_COMPILATION.sub(_blank, text)


def parse_cfr_citations(
    text: str, *, list_expansion: str = "plural-label"
) -> tuple[CfrCitation | CfrCitationRange, ...]:
    """Read single CFR coordinates and written endpoint pairs.

    Ranges return ``CfrCitationRange`` and must not be minted as one part.
    Unread/ambiguous scope returns a title-only coordinate here; use
    ``find_cfr_citations`` to retain the raw scope and its refusal reason.
    Neither reader enumerates a range or verifies legal existence.

    ``list_expansion`` decides when ", 61, and 63" continues a citation:

    ``"plural-label"`` (default)
        Only a plural label — "parts", "§§", "sections" — licenses expansion.
        Correct for PROSE, where a comma after "part 37" may belong to the
        sentence rather than the citation.

    ``"always"``
        Any comma-separated run continues the citation. Correct for a
        STRUCTURED field, where the whole value is the citation: in the
        Unified Agenda's CFR field, 953 references list parts with no label
        at all against 43 with a plural one, so the prose rule would drop
        the dominant shape.

    Title 3 compilation locators are excised before matching (see
    :func:`parse_eo_compilation_locators` to read them), and either policy
    stops a list at a number that leads another citation form.
    """

    return _parse_cfr_citations(text, list_expansion=list_expansion)


# Adjacent labels are source pinpoints; a separated "(2025)" is not consumed.
# Internal spacing is retained in the slice, including the CFR's "( 4 )".
_CFR_PINPOINT_LABEL = re.compile(r"\(\s*([0-9A-Za-z]{1,4})\s*\)")

_LOCAL_CLAUSE = re.compile(r"\b(?P<kind>clauses?)\s*(?P<label>\([^()\r\n]*\))", re.IGNORECASE)
_LOCAL_CLAUSE_SUFFIX = re.compile(
    r"\s*(?:\(|[-–—]|\b(?:of|in|under|through|to)\b|"
    r"(?:,\s*)?(?:(?:and|or)\s+)?(?:\(|clauses?\b))",
    re.IGNORECASE,
)
_LOCAL_SCOPE_BOUNDARY = re.compile(
    r"[.!?;]|\r?\n[ \t]*\r?\n|\b(?:section|subsection|paragraph|subparagraph|subclause)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocalClauseOccurrence:
    """A source mention, not an address or an assertion that a rule governs.

    Refusals retain the occurrence rather than silently shortening qualified
    forms into a bare label. The consumer must supply native structural scope.
    """

    label: str
    start: int
    end: int
    text: str
    refusal: str | None = None


def find_local_clause_occurrences(text: object) -> tuple[LocalClauseOccurrence, ...]:
    """Read singular, unqualified lowercase Roman clause labels with exact spans.

    Observed source: 20 USC 1414(d)(1)(C)(iii), whose agreement under clause (i)
    and consent under clause (ii) are ordinary text without publisher hyperlinks.
    Lists, ranges, attached pinpoints and stated containers require a broader
    grammar. Preserve them as refusals. A prior structural word in the same
    sentence is also conservative evidence against guessing the local parent.
    Scope boundaries are indexed once: O(text + occurrences * log(boundaries)).
    """
    document = "" if text is None else str(text)
    boundaries = list(_LOCAL_SCOPE_BOUNDARY.finditer(document))
    ends = [b.end() for b in boundaries]
    found: list[LocalClauseOccurrence] = []
    for marker in _LOCAL_CLAUSE.finditer(document):
        label_match = _CFR_PINPOINT_LABEL.fullmatch(marker.group("label"))
        label = label_match.group(1) if label_match else marker.group("label")[1:-1].strip()
        refusal = None
        if marker.group("kind").lower() != "clause" or re.fullmatch(r"[ivxlcdm]+", label) is None:
            refusal = "local_clause_label_unsupported"
        elif _CITATION_PARAGRAPH_BREAK.search(marker.group()):
            refusal = "local_clause_paragraph_break"
        else:
            suffix = _LOCAL_CLAUSE_SUFFIX.match(document, marker.end())
            if suffix and not _CITATION_PARAGRAPH_BREAK.search(document, marker.end(), suffix.end()):
                refusal = "local_clause_qualification_unsupported"
        previous = bisect_right(ends, marker.start()) - 1
        if previous >= 0 and boundaries[previous].group()[0].isalpha():
            refusal = "local_clause_container_unsupported"
        found.append(LocalClauseOccurrence(label, marker.start(), marker.end(), marker.group(), refusal))
    return tuple(found)


_CITATION_PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t]*\r?\n")
# A dash may introduce another complete label, but not a damaged word suffix.
_CFR_SUBPART_NAME = r"[A-Z]+(?!\w)(?!-(?![A-Z]+(?!\w)))"
_CFR_SUBPART = re.compile(
    rf"\s*,?\s*(?:(?i:appendix)\s+(?P<appendix>{_CFR_SUBPART_NAME})\s+(?i:to)\s+)?"
    rf"(?i:subpart)(?P<plural>(?i:s)?)\s+(?P<subpart>{_CFR_SUBPART_NAME})"
)
_CFR_SUBPART_ITEM = re.compile(
    rf"\s*(?:,\s*(?:(?i:and|or)\s+)?|(?i:and|or)\s+)"
    rf"(?P<label>(?i:subparts?)\s+)?(?P<subpart>{_CFR_SUBPART_NAME})"
)
_CFR_SUBPART_RANGE = re.compile(rf"\s*(?:[-–—]|(?i:to|through)\s+)\s*(?:(?i:subpart)\s+)?(?P<end>{_CFR_SUBPART_NAME})")
_CFR_SUBPART_CONTEXT = re.compile(r"[ \t]*\([^()\r\n]*\)")
# "The section notes that ..." uses a verb, not a note locator.
_CFR_NOTE_PROSE = re.compile(r"\s+(?:that|how|why|whether)\b", re.IGNORECASE)


def _qualify_cfr_item(
    text: str, base: CfrCitationOccurrence, *, expand_qualifiers: bool = True
) -> tuple[CfrCitationOccurrence, ...]:
    """Shared source qualifiers for forward and reverse explicit spellings."""
    found: list[CfrCitationOccurrence] = []

    def record(base: CfrCitationOccurrence) -> int:
        citation, start, end = base.citation, base.start, base.end
        context = None if base.context_start is None else (base.context_start, base.context_end)
        if (
            isinstance(citation, CfrCitation)
            and not base.refusal
            and citation.cfr_section is None
            and citation.cfr_part is not None
            and (subpart := _CFR_SUBPART.match(text, end)) is not None
            and not _CITATION_PARAGRAPH_BREAK.search(text, end, subpart.end())
        ):
            appendix = subpart.group("appendix")
            plural = bool(subpart.group("plural"))
            status = "ambiguous_part_scope" if context is not None else None
            while subpart is not None:
                end = subpart.end()
                range_end = None
                if (tail := _CFR_SUBPART_RANGE.match(text, end)) is not None and not _CITATION_PARAGRAPH_BREAK.search(
                    text, end, tail.end()
                ):
                    range_end, end = tail.group("end"), tail.end()
                if (description := _CFR_SUBPART_CONTEXT.match(text, end)) is not None:
                    end = description.end()
                found.append(
                    CfrCitationOccurrence(
                        citation,
                        start,
                        end,
                        text[start:end],
                        (),
                        context[0] if context else None,
                        context[1] if context else None,
                        subpart.group("subpart"),
                        range_end,
                        appendix,
                        status,
                    )
                )
                if range_end is not None:
                    break
                next_item = _CFR_SUBPART_ITEM.match(text, end)
                if (
                    next_item is None
                    or (not plural and not next_item.group("label"))
                    or _CITATION_PARAGRAPH_BREAK.search(text, end, next_item.end())
                ):
                    break
                # Keep the whole written anchor when a part list is ambiguous.
                if start == base.start:
                    context = (context[0] if context else start, end)
                plural = plural or (next_item.group("label") or "").strip().casefold() == "subparts"
                start, subpart = end, next_item
            return end
        found.append(base)
        return end

    def collect(base: CfrCitationOccurrence) -> int:
        before = len(found)
        end = record(base)
        # Reuse the authority reader's written scope lexemes. A note or an
        # open-ended continuation cannot be resolved as the bare coordinate.
        for pattern, refusal in (
            (_USC_NOTE_TAIL[True], "note_target_unresolved"),
            (_USC_OPEN_END_TAIL, "open_ended_reference_unresolved"),
        ):
            tail = pattern.match(text, end)
            if tail is None or _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end()):
                continue
            if pattern is _USC_NOTE_TAIL[True]:
                prose = _CFR_NOTE_PROSE.match(text, tail.end())
                if prose and not _CITATION_PARAGRAPH_BREAK.search(text, tail.end(), prose.end()):
                    continue
            end = tail.end()
            last = found[-1]
            found[-1] = replace(last, end=end, text=text[last.start : end], refusal=last.refusal or refusal)
        if not expand_qualifiers and len(found) > before:
            first = found[before]
            found[before:] = [
                replace(
                    first,
                    end=end,
                    text=text[first.start : end],
                    subpart=None,
                    subpart_end=None,
                    appendix=None,
                    refusal=first.refusal or first.qualifier_status or found[-1].refusal,
                )
            ]
        return end

    collect(base)
    return tuple(found)


def find_cfr_citations(
    text: str,
    *,
    list_expansion: str = "plural-label",
    expand_qualifiers: bool = True,
) -> tuple[CfrCitationOccurrence, ...]:
    """Read complete CFR coordinates and ranges with their exact source evidence.

    Source spelling, repeated occurrences and impossible-title verdicts survive.
    Explicit CFR citations only: no title or local paragraph target is inferred
    from document context. Attached pinpoints and subpart qualifiers are consumed
    before walking lists. Written range endpoints survive without expansion.
    List connectors and parenthetical qualifications remain in the source slice;
    their legal relationship is not inferred. Ambiguous part/subpart pairings
    and unsupported note/open-ended scope carry refusals rather than becoming
    definite addresses. The identity-only parser does not retain these tails.
    ``expand_qualifiers=False`` keeps one occurrence per coordinate while still
    consuming its complete qualifier text and retaining ambiguity verdicts.
    """
    found: list[CfrCitationOccurrence] = []

    def collect(base: CfrCitationOccurrence, *, qualified: bool = False) -> int:
        rows = (base,) if qualified else _qualify_cfr_item(text, base, expand_qualifiers=expand_qualifiers)
        found.extend(rows)
        return rows[-1].end

    _parse_cfr_citations(text, list_expansion=list_expansion, record=collect, expand_qualifiers=expand_qualifiers)
    return tuple(found)


def _cfr_coordinate(title: int, part: str | None, section: str | None = None) -> CfrCitation:
    part = _canonical_part(part)
    return CfrCitation(title, part, section, _cfr_title_is_possible(title), _part_is_plausible(part))


def _read_cfr_item(
    text: str,
    normalized: str,
    title: int,
    start: int,
    position: int,
    plural: bool,
    context: tuple[int, int] | None = None,
) -> CfrCitationOccurrence:
    """One anchored coordinate, its pinpoints and an optional written range end."""

    def points(at: int) -> tuple[tuple[str, ...], int]:
        labels = []
        while (label := _CFR_PINPOINT_LABEL.match(text, at)) is not None:
            labels.append(label.group(1))
            at = label.end()
        return tuple(labels), at

    def trim(at: int) -> int:
        while at > start and text[at - 1].isspace():
            at -= 1
        return at

    def unread_end(at: int) -> int:
        tail = _CFR_UNREAD_TOKEN.match(text, at)
        # The failed endpoint may lead another explicit citation. Preserve
        # its title for the outer scanner instead of absorbing that title.
        if tail is not None and _CFR_OTHER_CITATION_GUARD.match(normalized, tail.end()) is not None:
            return tail.end()
        return trim(at)

    def coordinate(match):
        item = _cfr_coordinate(title, match.group("part"), match.group("section"))
        problem = None
        if "-" in item.cfr_part and not (title == 41 and re.fullmatch(r"\d+-\d+", item.cfr_part)):
            problem = "ambiguous_hyphen"
        if item.cfr_section and re.search(r"-\d+\.", item.cfr_section):
            problem = "ambiguous_section_range"
        return item, problem

    citation = _cfr_coordinate(title, None)
    labels, end_labels, refusal = (), (), None
    end = position
    match = _CFR_COORDINATE.match(normalized, position)
    if match is None:
        # Preserve a damaged numeric coordinate; ordinary following prose is
        # not an unread identifier merely because it follows a CFR title.
        if position < len(text) and text[position].isdigit():
            tail = _CFR_UNREAD_TOKEN.match(text, position)
            end, refusal = (tail.end() if tail else position + 1), "unread_coordinate"
        else:
            end = trim(position)
    else:
        citation, refusal = coordinate(match)
        end = match.end()
        if (
            refusal == "ambiguous_hyphen"
            and plural
            and citation.cfr_section is None
            and re.fullmatch(r"\d+-\d+", citation.cfr_part)
        ):
            left, right = citation.cfr_part.split("-")
            citation = CfrCitationRange(_cfr_coordinate(title, left), _cfr_coordinate(title, right))
            refusal = None
        if isinstance(citation, CfrCitation) and citation.cfr_section is not None:
            labels, end = points(end)
        tail = _CFR_RANGE_CONNECTOR.match(normalized, end)
        if tail is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end()):
            end = tail.end()
            last = _CFR_COORDINATE.match(normalized, end)
            if last is None:
                end = unread_end(end)
                refusal = "range_end_unread"
            else:
                endpoint, problem = coordinate(last)
                end = last.end()
                if endpoint.cfr_section is not None:
                    end_labels, end = points(end)
                if isinstance(citation, CfrCitationRange):
                    refusal = "nested_range"
                else:
                    mixed = (citation.cfr_section is None) != (endpoint.cfr_section is None)
                    citation = CfrCitationRange(citation, endpoint)
                    refusal = refusal or problem or ("mixed_range_units" if mixed else None)
            # A third endpoint is unread scope, not permission to publish the
            # first pair as if it accounted for the complete written range.
            while (
                extra := _CFR_RANGE_CONNECTOR.match(normalized, end)
            ) is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, extra.end()):
                end = unread_end(extra.end())
                refusal = "nested_range"
    return CfrCitationOccurrence(
        citation,
        start,
        end,
        text[start:end],
        labels,
        context[0] if context else None,
        context[1] if context else None,
        range_end_pinpoint=end_labels,
        refusal=refusal,
    )


def _reverse_cfr_items(text, normalized, head, body_end, title_match, list_expansion, expand_qualifiers):
    """Read only a complete coordinate group directly followed by its CFR title."""
    if _CITATION_PARAGRAPH_BREAK.search(text, head.start(), head.end()):
        return ()
    title = int(title_match.group("title"))
    label = head.group("label")
    plural = _label_is_plural(label)
    rows, position, start = [], head.end(), head.start()
    while True:
        item = _read_cfr_item(
            text, normalized, title, start, position, plural, (head.start(), title_match.end()) if rows else None
        )
        coordinate = item.citation.start if isinstance(item.citation, CfrCitationRange) else item.citation
        if re.fullmatch(_SECTION_MARKER, label, re.IGNORECASE) and coordinate.cfr_section is None:
            return ()
        qualified = _qualify_cfr_item(text, item, expand_qualifiers=expand_qualifiers)
        rows.extend(qualified)
        position = qualified[-1].end
        if position == body_end:
            break
        if position > body_end or item.refusal:
            return ()
        separator = _CFR_REVERSE_LIST_ITEM.match(normalized, position)
        if (
            separator is None
            or _CITATION_PARAGRAPH_BREAK.search(text, position, separator.end())
            or _CFR_COORDINATE.match(normalized, separator.end()) is None
        ):
            return ()
        if not plural and list_expansion != "always" and separator.group("label") is None:
            return ()
        label = separator.group("label") or label
        plural = plural or _label_is_plural(label)
        start, position = position, separator.end()
    # The final written member includes the suffix; every member retains the
    # complete title-bearing group as context. A note after that shared title
    # cannot turn earlier list members into unqualified section targets.
    last = rows.pop()
    tail = _qualify_cfr_item(
        text,
        replace(last, end=title_match.end(), text=text[last.start : title_match.end()], refusal=None),
        expand_qualifiers=expand_qualifiers,
    )
    shared_refusal = tail[-1].refusal
    rows.extend(replace(row, refusal=last.refusal or row.refusal) for row in tail)
    end = rows[-1].end
    return tuple(
        replace(
            row,
            context_start=head.start() if len(rows) > 1 else None,
            context_end=end if len(rows) > 1 else None,
            refusal=row.refusal or shared_refusal,
        )
        for row in rows
    )


def _parse_cfr_citations(
    text: str,
    *,
    list_expansion: str,
    record: Callable[..., int] | None = None,
    expand_qualifiers: bool = True,
) -> tuple[CfrCitation | CfrCitationRange, ...]:
    if list_expansion not in {"plural-label", "always"}:
        raise ValueError(f"unknown list expansion policy: {list_expansion!r}")
    if states_nothing(text):
        return ()
    normalized = _excise_compilations(_normalize_dashes(text))
    citations: list[CfrCitation | CfrCitationRange] = []
    spans: list[tuple[int, int]] = []

    reverse_titles = []
    for prefix in _CFR_REVERSE_OF.finditer(normalized):
        title = _CFR_LONGHAND.match(normalized, prefix.end())
        if (
            title is not None
            and title.group("label") is None
            and not _CITATION_PARAGRAPH_BREAK.search(text, prefix.start(), title.end())
        ):
            reverse_titles.append((prefix.start(), title))
    title_starts = [start for start, _ in reverse_titles]

    def collect(item: CfrCitationOccurrence, *, qualified: bool = False) -> int:
        nonlocal latest_end
        # The identity-only API has no refusal column. A rejected start must
        # not escape as a complete single-part identifier through that API.
        citation = item.citation
        if item.refusal:
            head = citation.start if isinstance(citation, CfrCitationRange) else citation
            citation = _cfr_coordinate(head.cfr_title, None)
        citations.append(citation)
        end = item.end
        if record is not None:
            end = record(item, qualified=True) if qualified else record(item)
        spans.append((item.start, end))
        latest_end = max(latest_end, end)
        return end

    def overlaps(start, end):
        at = bisect_left(previous_starts, end) - 1
        return start < latest_end or (at >= 0 and previous_ends[at] > start)

    for pattern in (_CFR_STANDARD, _CFR_TITLE_PART, _CFR_REVERSE_HEAD, _CFR_LONGHAND):
        # Index previous spellings once. Within this source-ordered pass, only
        # the latest consumed end can overlap a later anchor. Prefix maxima
        # handle the nested complete-group and individual-member intervals.
        previous = sorted(spans)
        previous_starts = [start for start, _ in previous]
        previous_ends = list(accumulate((end for _, end in previous), max))
        latest_end = -1

        for match in pattern.finditer(normalized):
            if pattern is _CFR_REVERSE_HEAD:
                if match.start() < latest_end:
                    continue
                at = bisect_left(title_starts, match.end())
                if at == len(reverse_titles):
                    continue
                body_end, title_match = reverse_titles[at]
                if overlaps(match.start(), title_match.end()):
                    continue
                rows = _reverse_cfr_items(
                    text, normalized, match, body_end, title_match, list_expansion, expand_qualifiers
                )
                if rows:
                    for row in rows:
                        collect(row, qualified=True)
                    spans.append((match.start(), latest_end))
                continue
            if overlaps(match.start(), match.end()):
                continue
            title = int(match.group("title") or match.groupdict().get("title_cfr"))
            plural = _label_is_plural(match.group("label"))
            if pattern is _CFR_LONGHAND and match.group("label") is None:
                item = CfrCitationOccurrence(_cfr_coordinate(title, None), match.start(), match.end(), match.group())
            else:
                item = _read_cfr_item(text, normalized, title, match.start(), match.end(), plural)
            position = collect(item)
            if item.refusal or (list_expansion != "always" and not plural):
                continue
            context = (match.start(), position)
            while (separator := _CFR_LIST_ITEM.match(normalized, position)) is not None:
                if _CITATION_PARAGRAPH_BREAK.search(text, position, separator.end()):
                    break
                # Check the same whole-coordinate guard for the first member,
                # every list member and every range endpoint.
                if _CFR_COORDINATE.match(normalized, separator.end()) is None:
                    break
                item = _read_cfr_item(text, normalized, title, position, separator.end(), plural, context)
                position = collect(item)
                if item.refusal:
                    break
    return tuple(citations)


# --------------------------------------------------------------------------- #
# Authority parsing


#: Whole-value label repairs: damage to the LABEL of a citation whose numbers
#: are intact and unambiguous. Each is anchored to the entire value, so prose
#: can never donate one, and each names one operation over one label. Row
#: counts measured on the failed authority pool 2026-08-22.
#:
#: The whole-value anchor is what licenses relaxing guards the in-prose
#: patterns need: "Stat" must be capitalised inside a sentence because a
#: lowercase "stat" there is a word, but a value that is nothing except
#: "126 stat 11" is a citation whatever its case.
#:
#: ``_DAMAGED_USC_LABEL`` deliberately reads LESS than :data:`_USC_CODE_NAME`:
#: no "U.S. Code" longhand and no annotated edition, because a repair rewrites
#: the label it matched and must therefore recognize only what it can rewrite.
#: ``_DAMAGED_USC_TITLE`` is likewise tighter than the reading grammar's
#: ``\d+``: a whole-value repair is a stronger claim than a read, and the Code
#: has 54 titles. Eleven repairs spelled the label out by hand before this;
#: the differences among those eleven copies were accidental, and the one
#: difference that is NOT accidental — whether the label's terminal period is
#: consumed — is now visible as a ``\.?`` at each call site.
_DAMAGED_USC_LABEL = r"U\.?\s?S\.?\s?C"
_DAMAGED_USC_TITLE = r"\d{1,2}"

#: Every congress that has issued numbered Public Laws, spelled as an
#: alternation so a pattern can ask "is this half a Congress?". GENERATED from
#: the two constants rather than typed, because a bound written twice drifts:
#: the series-bounds audit found one stale copy already.
_NUMBERED_CONGRESS = "|".join(str(n) for n in range(PL_FIRST_NUMBERED_CONGRESS, CONGRESS_CURRENT + 1))

_WHOLE_VALUE_LABEL_REPAIRS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # "126 stat 11", "61 stat. 1180" (38 rows, 16 spellings) — the label
    # lowercased. Verified against the series: 126 Stat. 11 is 2012, 61 Stat.
    # 1180 is the Chicago Convention, both cited elsewhere in the same corpus
    # with the capital.
    (
        re.compile(r"^(\d{1,3})\s+stat(utes?|ue)?(\.?)\s+(\d{1,5})\b(.*)$"),
        r"\1 Stat\3 \4\5",
        "lowercase-statutes-label",
    ),
    # "47 U.S.C., sec. 151", "18 U.S.C, 1350", "10 U.S.C., ch. 903",
    # "5 USC, app 2" (15 rows, 9 spellings) — a comma in the slot where the
    # label ends. Wave 4 read it only before a section MARKER; the corpus
    # writes the same damage before a bare section, a chapter and an
    # appendix, and a comma there is never a list separator, because a list
    # separator has a citation on its left. Inert on the 41,378 distinct
    # values that already read except where it fires as its wave-4 self.
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?)\s*,\s*(?=\d|ch|app|sec|§)", re.IGNORECASE),
        r"\1 ",
        "stray-comma-after-usc-label",
    ),
    # "47 U.S.C . 154(j)" (8 rows) — the label's terminal period pushed off
    # its letters by a space. The wave-2 precedent is the same period in the
    # wrong place one slot earlier ("15. U.S.C. 78w(a)").
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL})\s+\.\s*", re.IGNORECASE),
        r"\1. ",
        "space-inside-usc-label",
    ),
    # "19 U.S.C.. 3314", "5 U.S.C.. 504" (3 rows) — the terminal period typed
    # twice, the stuttered-label family wave 3 named ("79 FR FR 54588").
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL})\.\.\s*", re.IGNORECASE),
        r"\1. ",
        "doubled-period-after-usc-label",
    ),
    # "21 .U.S.C. 387i", "49 .U.S.C 30111" (3 rows) — a period that belongs
    # to the title's own tail, migrated across the space onto the label.
    # Anchored on the SPACE, so "15. U.S.C. 78w(a)" — which the standard
    # pattern already reads — is untouched.
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE})\s+\.\s*({_DAMAGED_USC_LABEL})", re.IGNORECASE),
        r"\1 \2",
        "space-then-period-before-usc-label",
    ),
    # "12 U.S.C. U.S.C. 93a" (4 rows) — the label typed twice, exactly the
    # stuttered FR label of wave 3.
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?)\s+{_DAMAGED_USC_LABEL}\.?\s+", re.IGNORECASE),
        r"\1 ",
        "stuttered-usc-label",
    ),
    # "z49 USC 47508", "U42 U.S.C 7429", "f42 usc 1106 to 1110" (6 rows) — a
    # single stray letter in front of an otherwise complete citation, the
    # one-keystroke insertion whose deletion leaves a citation whose title is
    # in series and whose section the citing agency files under it (49 U.S.C.
    # 47508 at FAA, 42 U.S.C. 7429 at EPA, 42 U.S.C. 1106 at SSA).
    (
        re.compile(rf"^[A-Za-z]({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?\s+\d)", re.IGNORECASE),
        r"\1",
        "stray-letter-before-usc-title",
    ),
    # "3o USC 1201 et seq" (1 row) — the letter O standing in for the digit
    # zero, the mirror of the "E0 12250" homoglyph wave 3 adopted for the EO
    # label. 30 U.S.C. 1201 is SMCRA, and the row sits at the Office of
    # Surface Mining's own agency code. Zero of the 41,378 already-reading
    # values match the pattern, so the operator is measured inert.
    (
        re.compile(rf"^(\d)[oO](\s*{_DAMAGED_USC_LABEL}\.?\s+\d)", re.IGNORECASE),
        r"\g<1>0\2",
        "letter-o-for-zero-in-usc-title",
    ),
    # "15 USC 780-5(b)", "15 U.S.C. 780-10", "15 USC 780-11", "15 USC 780-3"
    # (10 values, 33 rows) — the SAME homoglyph one field over, in the section
    # rather than the title. The Exchange Act's §15O runs 78o-1 through 78o-11
    # and the corpus writes it both ways.
    #
    # Exactly one survivor, and both halves are pinned:
    #
    # * "15 U.S.C. 780-N" is absent from the oracle for every N the corpus
    #   states, while 78o-1…78o-11 are all real. Section 780 itself IS real
    #   ("Office of Private Grievances and Redress"), which is why the BARE
    #   spelling is left alone — only the compound is impossible.
    # * Six of the eight RINs that file "780-N" also file "78o-N", several at
    #   the same section: RIN 1505-AA70 writes "15 USC 780-5(b)" and
    #   "15 USC 78o-5(b)", 1505-AA53 writes "780-5(f)" and "78o-5(f)",
    #   1557-AB52 writes "780-5"/"780-3" and "78o-5"/"78o-3", 7100-AD70
    #   writes "780-11" and "78o-11".
    #
    # NOT GENERALISED, and the oracle is why: 30 real sections have a compound
    # stem ending in the DIGIT zero — 16 U.S.C. 760-1…760-12, 2 U.S.C. 60-1,
    # 8 U.S.C. 1440-1, 12 U.S.C. 640-1, 16 U.S.C. 460-1 and 470-1 — and
    # "16 U.S.C. 760-10" has the identical shape to "15 U.S.C. 780-10". A rule
    # written on the shape would rewrite a real section into nothing. The title
    # and the stem are the fence, and widening it needs a section-existence
    # oracle this module does not carry.
    (
        re.compile(rf"^(15\s*{_DAMAGED_USC_LABEL}\.?\s*)780(-\d)", re.IGNORECASE),
        r"\g<1>78o\2",
        "letter-o-for-zero-in-usc-section",
    ),
    # "47 (USC 201(b)", "12 (U.S.C. 2243)" (13 rows) — a parenthesis opened
    # between a title and its own label, where a parenthetical citation lost
    # its introducing prose. Only the opener is dropped: a trailing ")" left
    # over stays uncovered text, so the row reads partial rather than "ok".
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE})\s*\(\s*({_DAMAGED_USC_LABEL}\.?\s)", re.IGNORECASE),
        r"\1 \2",
        "paren-before-usc-label",
    ),
    # "42 USC (290dd-1)" (2 rows) — parentheses wrapping the section itself.
    # Anchored immediately after the label with no section in between, which
    # is what keeps it off the 6,274 values whose parentheses are subsections
    # ("12 USC 1431(a)").
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?)\s*\(\s*([0-9][^()]*)\)\s*$", re.IGNORECASE),
        r"\1 \2",
        "paren-around-usc-section",
    ),
    # "US Cost, Art II, sec 2" (7 rows) — one deleted letter in the
    # Constitution's own label, the "SC" for "USC" precedent. "Cost" is an
    # English word, which is why the repair is anchored to the whole value's
    # head AND requires the article-and-section shape the standard pattern
    # then reads.
    (
        re.compile(r"^(U\.?\s?S\.?)\s+Cost\b(?=[,\s]+Art)"),
        r"\1 Const",
        "dropped-n-in-constitution-label",
    ),
    # "16 USC et 1531 et seq" (6 rows) — the "et" of the value's own "et seq."
    # tail, stuttered forward into the section slot. The same shape as the
    # stuttered FR label wave 3 named ("79 FR FR 54588"), and licensed only
    # when the tail the word belongs to is actually there.
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?)\s+et\s+(\d.*\bet\s+seq)", re.IGNORECASE),
        r"\1 \2",
        "stuttered-et-before-section",
    ),
    # "31 USC PL 5311-5314" (2 rows) — a Public Law LABEL standing between a
    # code name and its own section span. The value lost twice: it minted a
    # Public Law numbered by a Congress that has never sat, and the stray
    # label blocked the U.S.C. reader from the Bank Secrecy Act, 31 U.S.C.
    # 5311-5314 — which the same office writes undamaged 68 times in this
    # corpus ("31 USC 5311 to 5314" x66, "31 USC 5311-5314" x2).
    #
    # The numbered series IS the fence, and it is why this is a reading rather
    # than a guess: no 5,311th Congress has legislated, so the Public Law
    # reading is impossible and the U.S.C. one covers the whole string —
    # exactly one survivor. Where the label is REAL the operator never sees
    # the row: "31 USC PL 107-56 Bank Secrecy Act" and three sibling spellings
    # (9 rows) cite the USA PATRIOT Act, which amended the Bank Secrecy Act,
    # and congress 107 sits inside the series. This is a DISAMBIGUATION
    # between two readings of the same digits, not a refusal: an out-of-series
    # Public Law standing alone ("PL 9909-499") is still recorded and flagged,
    # because nothing there competes with it.
    (
        re.compile(
            rf"^({_DAMAGED_USC_TITLE}\s*{_DAMAGED_USC_LABEL}\.?)\s*"
            rf"(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*"
            rf"(?!(?:{_NUMBERED_CONGRESS})\s*-)(\d+\s*-\s*\d+)\s*$",
            re.IGNORECASE,
        ),
        r"\1 \2",
        "stray-public-law-label-before-usc-section",
    ),
    # "49 SC 30166", "15 SC 78q(a)" (9 rows, 4 spellings) — a dropped U.
    # "SC" is one deletion from "USC" and from no other label this grammar
    # knows, the same uniqueness that licensed "E0 12250" for "EO 12250".
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE})\s+S\.?\s?C\.?\s+(\d)"),
        r"\1 USC \2",
        "dropped-u-in-usc-label",
    ),
    # "40 U.S. 550", "43 U.S. 1763", "7 U.S. 6g" (3 values, 9 rows) — a
    # dropped C, the sibling of the repair above. The first two were read as
    # SUPREME COURT CASES and published clean, flagged by nothing; the third
    # refused loudly. One operator answers both, because the damage is one
    # damage and only the competing reading differed.
    #
    # The case reading is refused by US citation practice itself: a case
    # citation names its case or its year, and a bare volume-reporter-page
    # with neither locates a decision nobody can name. All 20 of the other
    # case values in this corpus carry a party name, a year, or both.
    #
    # Exactly one survivor, and it is the PUBLISHER's own answer, taken from
    # the authority note of the rule's own CFR part (eCFR, fetched
    # 2026-08-22). Each value's own record corroborates it a second time, in
    # the siblings the same filer wrote with the C intact:
    #
    # * RIN 0991-AC14 revises 45 CFR part 12a — "Authority: 42 U.S.C. 11411;
    #   40 U.S.C. 550." The record's other authority is "42 U.S.C. 11411".
    # * RIN 1004-AF32 revises 43 CFR part 2800 — "Authority: 43 U.S.C. 1733,
    #   1740, 1763, 1764, and 3003." The record also writes "43 U.S.C. 1733"
    #   and "43 U.S.C. 1740".
    # * RIN 3038-AE36 revises 17 CFR 1.31 — part 1's authority note runs
    #   "7 U.S.C. 1a, 2, 5, 6, 6a, 6b, … 6f, 6g, 6h, …". The record writes
    #   six further title 7 sections beside it, every one spelled "U.S.C.".
    #
    # Whole-value anchored at BOTH ends, which is what keeps it off every real
    # case citation: "Touhy v. Ragen, 340 U.S. 462 (1951)" has a name in front
    # and a year behind, so this operator never sees it. Eight PERIODLESS
    # spellings of the same damage remain ("42 US 2201", "15 US 1392",
    # "50 US 2401 et seq", 8 values / 10 rows) and stay refused rather than
    # repaired: each would need its own record-level corroboration, and a
    # loud refusal is honest where a silent case citation was not.
    (
        re.compile(rf"^({_DAMAGED_USC_TITLE})\s+U\.\s?S\.\s+(\d[0-9A-Za-z]*(?:-[0-9A-Za-z]+)?)\s*$"),
        r"\1 USC \2",
        "dropped-c-in-usc-label",
    ),
    # "27 U.S.C. 1087", "27 USC 1087" and "Convention on International Trade in
    # Endangered Species of Wild Fauna and Flora (March 3, 1973), 27 USC 1087"
    # (3 values, 38 rows) — a C where the Treaty series writes a T. The same
    # one-letter substitution as the two repairs above, and the only repair
    # here whose survivor is a DIFFERENT citation family rather than a cleaner
    # spelling of the same one.
    #
    # Exactly one survivor, both halves measured:
    #
    # * The Code reading is impossible. Title 27 is Intoxicating Liquors and
    #   its highest section is 228 in any edition 1994-2026 — 39 enumerated
    #   sections topping out at 219a plus printed ranges ending "221 to 228" —
    #   so there is no 27 U.S.C. 1087 to mean (the pinned OLRC oracle in
    #   ``research/evidence/usc-section-oracle-2026-08-24``, 66,780 pairs).
    # * The treaty reading is real AND the corpus states it: 27 U.S.T. 1087 is
    #   CITES, and three further values / 12 rows write that same volume and
    #   page with the T intact ("27 U.S.T. 1087", "27 UST 1087, Convention on
    #   International Trade in Endangered Species…" and its inverted spelling).
    #   The third damaged value NAMES the Convention and still yielded a Code
    #   citation, which is the sharpest evidence in the set.
    #
    # The PAIR is the fence, which is why this entry may carry a prefix where
    # every other is anchored at its head: no prose donates "27 USC 1087", and
    # the prefix the corpus does write is the instrument's own name. It is not
    # generalised to "any impossible section" — this module holds no
    # section-existence oracle, and inventing one from a corpus ceiling would
    # license a repair on a heuristic. The reverse damage (a treaty label where
    # the Code was meant) has no specimen here and gets no operator.
    (
        re.compile(rf"^(.*?)\b27\s*{_DAMAGED_USC_LABEL}\.?\s*1087\s*$", re.IGNORECASE),
        r"\g<1>27 U.S.T. 1087",
        "code-label-on-a-treaty-series",
    ),
)


def _repair_whole_value_label(text: str) -> str:
    """Apply at most one named whole-value label repair, or return the text."""

    for pattern, replacement, _name in _WHOLE_VALUE_LABEL_REPAIRS:
        repaired, count = pattern.subn(replacement, text, count=1)
        if count:
            return repaired
    return text


@dataclass(frozen=True)
class UscCitationOccurrence:
    """A source USC mention, including qualifications the field view omits."""

    citation: AuthorityCitation
    start: int
    end: int
    text: str
    pinpoint: tuple[str, ...] = ()
    range_end_pinpoint: tuple[str, ...] = ()
    subchapter: str | None = None
    subchapter_end: str | None = None
    context_start: int | None = None
    context_end: int | None = None
    refusal: str | None = None


_USC_SUBCHAPTER_TAIL = re.compile(
    r"\s*,?\s*(?i:subchapter)(?P<plural>s)?\b"
    r"(?:\s+(?P<first>(?:[IVXLCDM]+|\d+[A-Za-z]?)(?:-[A-Z\d]+)*)(?![\w-])"
    r"(?:\s+(?i:to|through)\s+(?P<last>[IVXLCDM]+|\d+[A-Za-z]?)(?![\w-]))?)?"
)
# Preserve an unread attached continuation as a refusal, not a shorter identity.
# A final sentence period alone is not a token continuation.
_USC_UNREAD_TAIL = re.compile(r"(?:[\w.-]*\w)?(?:\([^()\s]+\))*")
# Unlike the whole-field _IGNORABLE_TAIL, a source occurrence must retain
# this scope marker inside prose, with the end of the range left unresolved.
_USC_OPEN_END_TAIL = re.compile(r"[\s,]*(?:et\s+seq\.?|and\s+following|ff\.?)(?!\w)", re.IGNORECASE)


def find_usc_citations(text: str) -> tuple[UscCitationOccurrence, ...]:
    """Locate qualified USC mentions using the existing authority matcher.

    Prose lists continue only across adjacent citation syntax. The field reader's
    wider list policy and identity-only results remain separate. Source spelling,
    repeated mentions, range interpretation and refusals survive; neither a valid
    token nor a supported title establishes existence in an edition.
    """
    found: list[UscCitationOccurrence] = []
    normalized = _normalize_dashes(text)

    def points(position):
        labels, end = [], position
        while True:
            start = _ACT_SPACE.match(text, end).end()
            if _CITATION_PARAGRAPH_BREAK.search(text, end, start):
                break
            label = _CFR_PINPOINT_LABEL.match(text, start)
            if label is None or (start > end and label.group(1).isdigit() and len(label.group(1)) == 4):
                break
            labels.append(label.group(1))
            end = label.end()
        return tuple(labels), end

    def record(citation, match, offset, span, context):
        start, end = span
        end = max(end, offset + match.end())
        while end > start and text[end - 1].isspace():
            end -= 1  # An optional appendix section can leave trailing space.
        groups = match.groupdict()
        section = "section" if groups.get("section") is not None else "first"
        labels, end_labels = (), ()
        if groups.get(section) is not None:
            labels, position = points(offset + match.end(section))
            end = max(end, position)
            if groups.get("range_end") is not None:
                end_labels, position = points(offset + match.end("range_end"))
                end = max(end, position)
            elif citation.usc_section_end is not None:
                end_labels, labels = labels, ()  # A label after "552-553" belongs to 553.
        refusal = None
        note = _USC_NOTE_TAIL[True].match(text, end)
        if note is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, note.end()):
            citation, end = replace(citation, usc_note=True), note.end()
            if note.group("position"):
                refusal = "usc_note_position_unresolved"
        subchapter = subchapter_end = None
        if citation.usc_chapter is not None:
            tail = _USC_SUBCHAPTER_TAIL.match(normalized, end)
            if tail is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end()):
                subchapter, subchapter_end, end = tail.group("first"), tail.group("last"), tail.end()
                if subchapter is None:
                    refusal = "usc_subchapter_unresolved"
                elif tail.group("plural") and "-" in subchapter and subchapter_end is None:
                    # The plural marker distinguishes written endpoints from
                    # a singular compound label such as subchapter I-A.
                    endpoints = subchapter.split("-")
                    if len(endpoints) == 2:
                        subchapter, subchapter_end = endpoints
                    else:
                        refusal = "usc_subchapter_unresolved"
                if citation.usc_chapter_end is not None:
                    refusal = "usc_subchapter_scope_ambiguous"
        tail = _USC_UNREAD_TAIL.match(text, end)
        if tail is not None and tail.end() > end:
            end, refusal = tail.end(), "usc_token_continuation_unresolved"
        if groups.get("range_end") is not None and citation.usc_section_end is None:
            refusal = "usc_range_unresolved"
        continuation = _USC_OPEN_END_TAIL.match(text, end)
        if continuation is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, continuation.end()):
            end, refusal = continuation.end(), "usc_open_ended_reference_unresolved"
        if start and text[start].isalnum() and (text[start - 1].isalnum() or text[start - 1] == "_"):
            while start and (text[start - 1].isalnum() or text[start - 1] == "_"):
                start -= 1
            refusal = "usc_token_boundary_unresolved"
        if not usc_title_is_possible(citation.usc_title):
            refusal = "usc_title_outside_supported_space"
        found.append(
            UscCitationOccurrence(
                citation,
                start,
                end,
                text[start:end],
                labels,
                end_labels,
                subchapter,
                subchapter_end,
                context[0] if context else None,
                context[1] if context else None,
                refusal,
            )
        )
        return end

    _parse_authority_citation(text, usc_record=record)
    return tuple(sorted(found, key=lambda item: (item.start, item.end)))


@dataclass(frozen=True)
class AuthorityCitationOccurrence:
    """A Public Law or Statutes at Large citation with its exact, codepoint-indexed source slice."""

    citation: AuthorityCitation
    start: int
    end: int
    text: str


def find_public_law_citations(text: str) -> tuple[AuthorityCitationOccurrence, ...]:
    """Locate every Public Law a text cites, read by the patterns and fields the field reader uses.

    Added in spicy-docs (2026-09-23) beside :func:`find_usc_citations` and
    :func:`find_cfr_citations`, which already locate their families in running
    text. The match runs over the dash-folded text, as the field reader's prose
    pass does; the fold is one character for one, so every span indexes
    ``text`` itself. Every occurrence is kept, repeated mentions included.
    """
    normalized = _normalize_dashes(text)
    found = [
        AuthorityCitationOccurrence(
            AuthorityCitation(**_public_law_fields(match)),
            match.start(),
            match.end(),
            text[match.start() : match.end()],
        )
        for pattern in _PUBLIC_LAW_FORMS
        for match in pattern.finditer(normalized)
    ]
    return tuple(sorted(found, key=lambda item: (item.start, item.end)))


def find_statute_citations(text: str) -> tuple[AuthorityCitationOccurrence, ...]:
    """Locate every Statutes at Large page a text cites, by :data:`_STATUTE_FAMILIES`.

    The companion of :func:`find_public_law_citations`, over the same folded
    text. A lettered page's span covers exactly what its row carries, a range
    tail included; each volume carries the same neighbour verdict the field
    reader gives it, against the Public Laws this text states.
    """
    normalized = _normalize_dashes(text)
    public_laws = [match for pattern in _PUBLIC_LAW_FORMS for match in pattern.finditer(normalized)]
    verdict = _statutes_volume_verdict(normalized, public_laws)
    found: list[AuthorityCitationOccurrence] = []
    for pattern, fields, covered_end in _STATUTE_FAMILIES:
        for match in pattern.finditer(normalized):
            end = match.end() if covered_end is None else covered_end(match)
            found.append(
                AuthorityCitationOccurrence(
                    AuthorityCitation(**fields(match, verdict)), match.start(), end, text[match.start() : end]
                )
            )
    return tuple(sorted(found, key=lambda item: (item.start, item.end)))


def parse_authority_citation(text: str) -> tuple[AuthorityCitation, ...]:
    """Read every legal authority in one string, with a status instead of silence.

    Every input yields at least one result: unreadable text is retained as an
    ``other``/``failed`` row, and a citation embedded in extra prose is
    ``partial`` rather than discarded. The Unified Agenda's
    ``LEGAL_AUTHORITY_LIST`` carries 755,727 of these.

    The families are read in a fixed order, and three places in that order are
    load-bearing rather than incidental: the U.S.C. appendix form is read
    before the plain one, the unnamed-instrument treaty read follows the
    series ones it defers to, and the whole-value fallbacks run only after
    everything else has read nothing. Every other family is independent of
    every other, and the order it happens to sit in is the order its rows are
    published in — which the Agenda tables carry as ``ordinal``, so it is not
    free to change.
    """

    return _parse_authority_citation(text)


def _parse_authority_citation(
    text: str, *, usc_record: Callable[..., int] | None = None
) -> tuple[AuthorityCitation, ...]:
    normalized = (
        _normalize_dashes(text)
        if usc_record is not None
        else _repair_whole_value_label(_normalize_dashes(text.strip()))
    )
    if states_nothing(normalized):
        # A placeholder is not a failed parse: the publisher said nothing.
        return (AuthorityCitation(authority_type="unstated", parse_status="failed"),)

    citations: list[AuthorityCitation] = []
    seen: set[AuthorityCitation] = set()

    usc_ends: dict[int, int] = {}

    def _add(citation: AuthorityCitation, match=None, *, offset=0, span=None, context=None):
        # An EXPANDED span is never "ok", and the rule saying so is here rather
        # than at each of the six places a section citation is constructed.
        # "ok" means this module accounts for the whole string, and for an
        # abbreviation it would also be claiming the sections BETWEEN the two
        # endpoints — a claim the grammar cannot check, because the
        # section-existence oracle imports this module and so cannot be
        # imported by it. Five of the 68 abbreviated tokens in the pinned
        # corpus expand to spans that are mostly not law; the status is what a
        # consumer filtering on "ok" sees without reading this file.
        if citation.usc_section_span_rule == USC_SPAN_ABBREVIATED and citation.parse_status == "ok":
            citation = replace(citation, parse_status="partial")
        if citation not in seen:
            seen.add(citation)
            citations.append(citation)
        if usc_record is not None and match is not None and citation.authority_type in ("usc", "usc_chapter"):
            span = span or (offset + match.start(), offset + match.end())
            end = usc_record(citation, match, offset, span, context)
            usc_ends[span[0]] = end
            return end
        return None

    def _read(
        pattern: re.Pattern[str],
        fields: Callable[[re.Match[str]], dict[str, Any]],
        *,
        status: str | None = None,
        covered_end: Callable[[re.Match[str]], int] | None = None,
    ) -> list[re.Match[str]]:
        """Emit one row per match of ``pattern``, statused by what it covered.

        One sentence, written once: a match is a row, and a row is "ok" only
        when its own span leaves nothing behind but an ignorable tail. Twenty
        families restated that sentence by hand before this, which is twenty
        chances for one restatement to drift from the other nineteen.

        ``covered_end`` is for a family that CONSUMES more than it carries — a
        range tail the ordering rule declines, a dropped end leaf — where the
        uncovered characters must still count against "ok". ``status`` is for
        a family that can never cover a whole value whatever it matched.
        """

        matches = list(pattern.finditer(normalized))
        for match in matches:
            end = match.end() if covered_end is None else covered_end(match)
            _add(
                AuthorityCitation(
                    parse_status=status or _status_for_span(normalized, match.start(), end),
                    **fields(match),
                ),
                match,
                span=(match.start(), end),
            )
        return matches

    # The appendix form is read FIRST and its spans fence the plain form off:
    # "50 U.S.C. app. 2401" must not also read as plain 50 U.S.C. 2401, which
    # is a different place. Measured over the 42,642 distinct authority values
    # the Agenda carries, the fence never fires — "app" is not a section
    # marker, so _USC_STANDARD reads nothing inside an appendix citation. The
    # fence stays anyway: what makes it inert is a property of the marker set,
    # and the marker set is exactly the kind of thing a later reader widens.
    appendix_matches = _read(
        _USC_APPENDIX,
        lambda m: {
            "authority_type": "usc",
            "usc_title": int(m.group("title")),
            "usc_appendix": True,
            **_usc_section_fields(m.group("section")),
        },
    )
    appendix_spans = [match.span() for match in appendix_matches]

    # A U.S.C. match may consume more or less text than it carries, and both
    # move where its coverage ends: a range tail the ordering rule declines is
    # consumed and dropped, and a statutory note is law printed under the
    # section — carried as a flag, and therefore covered rather than left as
    # an uncovered tail. This is the one family whose span is not its match.
    usc_matches: list[re.Match[str]] = []
    for pattern, named_title in _USC_CODE_FORMS:
        matches = list(pattern.finditer(normalized))
        if pattern is _USC_STANDARD:
            usc_matches = matches
        for match in matches:
            if any(start <= match.start() and match.end() <= end for start, end in appendix_spans):
                continue
            # The match still stands (it seeds :data:`_USC_LIST_TAIL`'s scan
            # from wherever it ends) even when the section it carries is a
            # CFR regulation number truncated at the dot rather than a real
            # Code section — see ``_usc_leading_section_is_untruncated`` and
            # :data:`_A_DOTTED_NUMBER_IS_A_CFR_SECTION`. Only the fabricated
            # row is withheld.
            if usc_record is None and not _usc_leading_section_is_untruncated(normalized, match):
                continue
            fields = _usc_section_fields(match.group("section"), match.groupdict().get("range_end"))
            covered_end = (
                match.end("section")
                if match.groupdict().get("range_end") is not None and fields["usc_section_end"] is None
                else match.end()
            )
            note = _USC_NOTE_TAIL[False].match(normalized, covered_end)
            if note is not None:
                covered_end = note.end()
            title = match.groupdict().get("title")
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status=_status_for_span(normalized, match.start(), covered_end),
                    usc_title=int(title) if title else named_title,
                    usc_note=note is not None,
                    **fields,
                ),
                match,
                span=(match.start(), covered_end),
            )

    # The transposed label: "21 UCS 374" is 21 U.S.C. 374 (uppercase only;
    # adjacent transposition is the named operator). "UCS" is unreachable by
    # _USC_CODE_NAME, so this family shadows no true spelling whatever order
    # it is read in.
    _read(
        _USC_TRANSPOSED_LABEL,
        lambda m: {
            "authority_type": "usc",
            "usc_title": int(m.group("title")),
            **_usc_section_fields(m.group("section")),
        },
    )

    for match in _USC_TITLE_FORM.finditer(normalized):
        title = int(match.group("title"))
        _add(
            AuthorityCitation(
                authority_type="usc",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                usc_title=title,
                **_usc_section_fields(match.group("first")),
            ),
            match,
        )
        # A listed member is never covered by the head's span, so it is
        # partial whatever the head was.
        for item in _USC_TITLE_FORM_ITEM.finditer(match.group("items") or ""):
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status="partial",
                    usc_title=title,
                    usc_section=_usc_section(item.group("section")),
                ),
                item,
                offset=match.start("items"),
                context=match.span(),
            )

    # A deviation from citations.py, which kept chapters out of the authority
    # parse entirely: the Agenda's authority field does cite chapters, and a
    # typed row beats an "other/failed" one.
    _read(
        _USC_CHAPTER,
        lambda m: {
            "authority_type": "usc_chapter",
            "usc_title": int(m.group("title")),
            "usc_chapter": m.group("chapter").lower(),
            "usc_chapter_end": (m.group("chapter_end") or "").lower() or None,
        },
    )

    public_law_matches: list[re.Match[str]] = []
    for pattern in _PUBLIC_LAW_FORMS:
        public_law_matches += _read(pattern, _public_law_fields)

    # The one verdict that reads a NEIGHBOUR rather than its own match: a
    # Statutes volume is judged against the Public Law standing beside it,
    # because neither half is checkable alone.
    #
    # It is written HERE, once, because TWO readers below mint the
    # ``statute_volume`` column and the verdict lived inside one of them. The
    # lettered-page reader minted a volume with a permanently NULL verdict —
    # 30 distinct values / 369 rows of the pinned table, of which 24 values /
    # 328 rows state exactly one Public Law in the same string (measured
    # 2026-08-22). Whether a citation is judged now depends on the citation
    # and not on which reader happened to match it.
    #
    # The lettered-VOLUME reader is deliberately not a third caller: "70A
    # Stat." leaves ``statute_volume`` NULL because 70A is not volume 70, and
    # this relation judges the integer series.
    _volume_verdict = _statutes_volume_verdict(normalized, public_law_matches)

    for pattern, fields, covered_end in _STATUTE_FAMILIES:
        _read(pattern, lambda m, fields=fields: fields(m, _volume_verdict), covered_end=covered_end)

    for pattern in (_EXECUTIVE_ORDER_SPELLED, _EXECUTIVE_ORDER_ABBREVIATED):
        for match in pattern.finditer(normalized):
            _add(
                AuthorityCitation(
                    authority_type="executive_order",
                    parse_status=_status_for_span(normalized, match.start(), match.end()),
                    executive_order=str(int(match.group("number"))),
                )
            )
            # A number list continues the citation: "Executive Orders 13990
            # and 14008" names two orders, and reading one is dropping one.
            # No plural label is demanded, and the corpus is why — "E.O.
            # 11302, 13520" and "EO 10577, 11222, 11478, and 12106" write the
            # label singular and list anyway (3 distinct values, measured
            # 2026-08-22). This is the Agenda's structured field, where the
            # whole value is the citation, so it takes the same "always"
            # policy parse_cfr_citations offers that field.
            position = match.end()
            while (item := _EXECUTIVE_ORDER_LIST_TAIL.match(normalized, position)) is not None:
                _add(
                    AuthorityCitation(
                        authority_type="executive_order",
                        parse_status="partial",
                        executive_order=str(int(item.group("number"))),
                    )
                )
                position = item.end()

    _read(
        _CASE_REPORTER,
        lambda m: {
            "authority_type": "case_citation",
            "case_reporter": re.sub(r"\s+", " ", m.group("reporter")).strip(),
            "case_volume": int(m.group("volume")),
            "case_page": int(m.group("page")),
        },
    )
    _read(
        _CASE_US_PERIODLESS,
        lambda m: {
            "authority_type": "case_citation",
            "case_reporter": "U. S.",
            "case_volume": int(m.group("volume")),
            "case_page": int(m.group("page")),
        },
    )

    _read(
        _PROCLAMATION,
        lambda m: {
            "authority_type": "presidential_document",
            "presidential_doc_kind": "proclamation",
            "proclamation": str(int(m.group("number"))),
        },
    )
    for pattern, kind in _PRESIDENTIAL_DOCUMENT_KINDS:
        # Date-identified documents carry a kind and no number, so the match
        # never covers the value that states the date: partial always.
        _read(
            pattern,
            lambda _m, kind=kind: {"authority_type": "presidential_document", "presidential_doc_kind": kind},
            status="partial",
        )

    _read(
        _OMB_INSTRUMENT,
        lambda m: {
            "authority_type": "administrative_order",
            # "Memoranda" is the plural of one instrument, not a second one.
            "admin_order_kind": "OMB " + ("Memorandum" if m.group("kind").startswith("Memorand") else m.group("kind")),
            "admin_order_number": m.group("number"),
        },
    )
    _read(
        _DEPARTMENTAL_MANUAL,
        lambda m: {
            "authority_type": "administrative_order",
            "admin_order_kind": "Departmental Manual",
            "admin_order_number": f"{m.group('part')} DM {m.group('chapter')}",
        },
    )
    for pattern, directive_kind in _DIRECTIVE_SYSTEMS:
        _read(
            pattern,
            lambda m, kind=directive_kind: {
                "authority_type": "administrative_order",
                "admin_order_kind": kind,
                "admin_order_number": m.group("number"),
            },
        )
    for match in _read(
        _ADMINISTRATIVE_ORDER,
        lambda m: {
            "authority_type": "administrative_order",
            "admin_order_kind": re.sub(r"\s+", " ", m.group("kind")).replace("’", "'").rstrip("s"),
            "admin_order_number": re.sub(r"\s", "", m.group("number")),
        },
    ):
        # A listed order is never covered by the head's span, so it is partial
        # whatever the head was — the Executive Order list's own posture.
        kind = re.sub(r"\s+", " ", match.group("kind")).replace("’", "'").rstrip("s")
        position = match.end()
        while (item := _ADMINISTRATIVE_ORDER_LIST_TAIL.match(normalized, position)) is not None:
            _add(
                AuthorityCitation(
                    authority_type="administrative_order",
                    parse_status="partial",
                    admin_order_kind=kind,
                    admin_order_number=re.sub(r"\s", "", item.group("number")),
                )
            )
            position = item.end()

    series_read = False
    for pattern, series in _TREATY_SERIES:
        matched = _read(
            pattern,
            lambda m, series=series: {
                "authority_type": "treaty",
                "treaty_series": series,
                "treaty_volume": int(m["volume"]) if m.groupdict().get("volume") else None,
                "treaty_number": (
                    f"{m['congress']}-{m['number']}" if m.groupdict().get("congress") else m.groupdict().get("number")
                ),
                "treaty_page": int(m["page"]) if m.groupdict().get("page") else None,
            },
        )
        series_read = series_read or bool(matched)

    # An instrument named without a series token — CITES, the Chicago
    # Convention, the Compacts of Free Association — is typed by kind alone,
    # the presidential-memoranda convention: partial always, the name in the
    # original text, no series identifier minted. It defers to a series token
    # in the same value (3 distinct values carry both, measured 2026-08-22),
    # which is why it is read after them and not before.
    if not series_read:
        _read(_TREATY_INSTRUMENT_NAME, lambda _m: {"authority_type": "treaty"}, status="partial")

    _read(
        _REVISED_STATUTES,
        lambda m: {"authority_type": "revised_statute", "revised_statute_section": m.group("section")},
    )

    for match in _DC_CODE_ANCHOR.finditer(normalized):
        position = match.end()
        sections: list[str] = []
        if match.group("title") is not None:
            # The older title-first spelling: "26 DC Code 102" is title 26,
            # section 102 — the same compound the modern form writes "26-102",
            # read to it the way the inverted U.S.C. appendix order is.
            bare = _DC_CODE_BARE_SECTION.match(normalized, position)
            if bare is not None:
                sections.append(f"{int(match.group('title'))}-{bare.group('section')}")
                position = bare.end()
        else:
            while (item := _DC_CODE_SECTION.match(normalized, position)) is not None:
                sections.append(item.group("section"))
                position = item.end()
        if sections:
            status = _status_for_span(normalized, match.start(), position)
            for section in sections:
                _add(
                    AuthorityCitation(
                        authority_type="dc_code",
                        parse_status=status,
                        dc_code_section=section,
                    )
                )
        else:
            # Naming the Code without a readable section still types the row.
            _add(AuthorityCitation(authority_type="dc_code", parse_status="partial"))

    _read(
        _CONSTITUTION,
        lambda m: {
            "authority_type": "constitution",
            "constitution_article": m.group("article"),
            "constitution_section": m.group("section"),
        },
    )

    # A Title 3 compilation locator cited AS the authority — the grammar for
    # it predates this loop and was simply never wired here.
    for locator in parse_eo_compilation_locators(normalized):
        _add(
            AuthorityCitation(
                authority_type="eo_compilation",
                parse_status="partial",
                eo_compilation_start=locator.compilation_start,
                eo_compilation_page=locator.page,
            )
        )
    # A compilation fragment that lost its "3 CFR" head: "1991 Comp p 351".
    # Whole-value only; the year may be gone too ("Comp., p. 193"), and a
    # locator missing its volume is partial like every other.
    _read(
        _COMPILATION_FRAGMENT,
        lambda m: {
            "authority_type": "eo_compilation",
            "eo_compilation_start": m.group("year"),
            "eo_compilation_page": m.group("page"),
        },
        status="partial",
    )

    _read(
        _REORGANIZATION_PLAN,
        lambda m: {
            "authority_type": "reorganization_plan",
            "reorganization_plan": f"{int(m.group('number'))}-of-{m.group('year')}",
        },
    )

    # A CFR citation in the authority field is a real citation in the wrong
    # column — 7,092 of them, "delegation of authority at 49 CFR 1.95" the
    # commonest. Typed as what it is rather than left "failed"; the field's
    # semantics stay the consumer's question. A part-less citation still names
    # its title: "3 CFR" and "48 CFR ch 1" are 63 Agenda authority values, and
    # the title is what they state.
    for occurrence in find_cfr_citations(normalized, expand_qualifiers=False):
        citation = occurrence.citation
        cfr = citation.start if isinstance(citation, CfrCitationRange) else citation
        endpoint = citation.end if isinstance(citation, CfrCitationRange) else None
        if not cfr.title_is_possible:
            continue
        _add(
            AuthorityCitation(
                authority_type="cfr",
                parse_status="partial",
                cfr_title=cfr.cfr_title,
                cfr_part=cfr.cfr_part,
                cfr_section=cfr.cfr_section,
                cfr_part_is_plausible=cfr.part_is_plausible,
                cfr_part_end=endpoint.cfr_part if endpoint else None,
                cfr_section_end=endpoint.cfr_section if endpoint else None,
                cfr_end_part_is_plausible=endpoint.part_is_plausible if endpoint else None,
                cfr_refusal=(
                    occurrence.refusal
                    or occurrence.qualifier_status
                    or (
                        "range_pinpoints_not_represented"
                        if endpoint is not None and (occurrence.pinpoint or occurrence.range_end_pinpoint)
                        else None
                    )
                ),
            )
        )

    # A regulation that cites itself by its own name, where the instrument
    # publishes the equivalence to a CFR part: FAR 1.105-2 declares "(FAR) 48
    # CFR 1.301" the parallel form, and the OFR prints "DFARS Part 201" in the
    # heading of 48 CFR 201. Both are whole-value only, so the English word
    # "far" can never donate one, and both are the same claim — a self-named
    # part IS the title 48 part — so they are one table rather than two blocks.
    for pattern in (_FAR_SELF_CITATION, _DFARS_SELF_CITATION):
        _read(
            pattern,
            lambda m: {
                "authority_type": "cfr",
                "cfr_title": 48,
                "cfr_part": m.group("part"),
                # Both self-citations read the section after the dot, and both
                # threw it away for want of a column: "FAR 1.105-2" is not
                # part 1 wholesale, and neither is "DFARS 201.3".
                "cfr_section": m.group("section"),
                "cfr_part_is_plausible": _part_is_plausible(m.group("part")),
            },
            status="partial",
        )

    # A Federal Register citation in the authority field is, like the CFR
    # family above, a real citation in the wrong column: "44 FR 56673" is a
    # published document's address. 101 distinct unreadable values carried
    # at least one (measured 2026-08-21); always partial, because locating a
    # document is not covering an authority string.
    for fr_citation in parse_federal_register_citations(normalized):
        _add(
            AuthorityCitation(
                authority_type="federal_register",
                parse_status="partial",
                fr_volume=fr_citation.volume,
                fr_page=fr_citation.page,
            )
        )

    # A section list is never covered by a single citation, so every listed
    # member is partial. A listed member may itself be a range
    # ("42 U.S.C. 7401, 7671a-7671q"), split by the same ordering rule. The
    # window stops at the next citation's head so one title's list cannot run
    # into another's.
    #
    # A comma inside a DATE or inside an ACT'S NAME is not a list separator,
    # and this walk is the only one in the module that ever reaches one:
    # measured over all 42,642 distinct authority values, no CFR part list,
    # Executive Order list, D.C. Code list or "of title" list crosses either
    # shape, because each of those is walked anchored and stops at the word.
    # So the fence lives here, where the casualties are, rather than in the
    # shared separator.
    #
    # An APPENDIX citation seeds a list on exactly the same terms as a plain
    # one. It did not before, because only _USC_STANDARD matches were seeds,
    # and the omission dropped real citations: "46 app USC 808, 839" published
    # 808 alone, where both are sections of the Shipping Act, 1916 as it stood
    # in 46 App. U.S.C. 16 distinct values, 38 source rows, measured
    # 2026-08-22. A listed member inherits the appendix flag, because a
    # title's appendix is a different body of law from the title proper and
    # half a list must not land in the other one.
    named = _spans_owning_their_comma(normalized)
    # And the third thing a bare number behind a comma can be: the agency half
    # of a RIN the filer is naming. See :data:`_RIN_TOKEN` for the measurement
    # and for the Register-document shape that was measured and NOT fenced.
    rins = tuple(match.span() for match in _RIN_TOKEN.finditer(normalized))
    # And the fourth: a YEAR or a PAGE inside a Title 3 compilation locator.
    # "31 USC 9701; 3 CFR, 1982 Comp., p. 166" cites the fee statute and the
    # page E.O. 12356 was printed on, and this walk read the volume's year as
    # a listed section of title 31 (13 rows of 31 U.S.C. 1982) and, in the
    # sibling value that writes the page bare, the page too (7 rows of 31
    # U.S.C. 166). Neither number is a section of anything: the locator names
    # a VOLUME and a PAGE, the family beside this one already types it as
    # such, and this module's own compilation grammar has read that span since
    # the CFR reader needed it — the list walk was simply never told.
    #
    # The fence is the locator's whole span, not its year: "E.O. 10577, 3 CFR,
    # 1954-58 Comp., p. 218" hands the walk "1954-58", which the ordering rule
    # then expands into an abbreviated SPAN of five sections. One rule covers
    # the year, the abbreviated closing year, the span between them and the
    # page, because all four are numbers the locator owns.
    compilations = tuple(match.span() for match in _EO_COMPILATION.finditer(normalized))
    # A FIFTH thing a bare number behind a comma can be, and the one this
    # walk cannot settle by itself: the SAME Statutes-at-Large citation's own
    # pinpoint page. "12 U.S.C. 2013, ...; sec. 301(a), Pub. L. 100-233, 101
    # Stat. 1568, 1608, as amended by ..., 102 Stat 989, 993" (12 CFR 615's
    # own authority note) publishes 12 U.S.C. 1608 and 12 U.S.C. 993 — both
    # are the Act's own second page (Bluebook "volume Stat. start, pinpoint"),
    # not sections of anything, and :data:`_STATUTE_AT_LARGE` has no tail of
    # its own to claim them the way :data:`_STATUTE_LETTERED_PAGE` does for
    # the lettered volumes. Measured 2026-09-01: 3 fabrications in this ONE
    # note alone (research/investigations-mined-2026-08-31.md item 4).
    #
    # UNLIKE the other four, this is not skipped outright: the trap is real.
    # 14 CFR 121's own note is IDENTICAL in shape — "... preceding note added
    # by Pub. L. 112-95, sec. 412, 126 Stat. 89, 44101, 44701-44702, 44705,
    # 44709-44711, 44713, ..." — and genuinely resumes a real 49 U.S.C. list
    # (44101, 44701, 44702, ... are all real aviation-safety sections) after
    # the Stat. citation. This module cannot tell the two apart by shape: it
    # has no section-existence oracle to ask (the oracle imports this module,
    # so the reverse is circular) and no way to know a Bluebook pinpoint page
    # from a resumed list item. So the fact is MARKED
    # (:attr:`AuthorityCitation.usc_section_after_statute`) rather than
    # decided, and a consumer that CAN reach the oracle gates admission on
    # it — see :func:`refspec.registry.cfr_authority_notes.read_note_citations`.
    statutes = tuple(
        match.span()
        for pattern in (_STATUTE_LETTERED_PAGE, _STATUTE_LETTERED_VOLUME, _STATUTE_AT_LARGE)
        for match in pattern.finditer(normalized)
    )
    # The same four questions, indexed once: a list member is asked each of
    # them, and a scan over every span per member was quadratic in a document.
    fenced = _containment((*named, *rins, *compilations))
    statute_opens = sorted(statutes)
    statute_starts = [start for start, _ in statute_opens]
    # The earliest any Statutes cite opening at or after each position closes.
    statute_first_close = list(accumulate((end for _, end in reversed(statute_opens)), min))[::-1]
    seeds = sorted(
        [(match, False) for match in usc_matches] + [(match, True) for match in appendix_matches],
        key=lambda seed: seed[0].start(),
    )
    for index, (match, in_appendix) in enumerate(seeds):
        stop = seeds[index + 1][0].start() if index + 1 < len(seeds) else len(normalized)
        window = match.end()
        position = usc_ends.get(match.start(), window)
        for tail in _USC_LIST_TAIL.finditer(normalized[window:stop]):
            if usc_record is not None:
                tail_start = window + tail.start()
                if tail_start < position:
                    continue
                gap = normalized[position:tail_start]
                if gap.strip(" \t\r\n,") or _CITATION_PARAGRAPH_BREAK.search(gap):
                    break
            start, end = window + tail.start("section"), window + tail.end("section")
            if fenced(start, end):
                continue
            fields = _usc_section_fields(tail.group("section"), tail.group("range_end"))
            if fields["usc_section"] is not None:
                first = bisect_left(statute_starts, window)
                after_statute = first < len(statute_opens) and statute_first_close[first] <= window + tail.start()
                occurrence_end = _add(
                    AuthorityCitation(
                        authority_type="usc",
                        parse_status="partial",
                        usc_title=int(match.group("title")),
                        usc_appendix=in_appendix,
                        usc_section_after_statute=after_statute,
                        **fields,
                    ),
                    tail,
                    offset=window,
                    context=(match.start(), position),
                )
                if occurrence_end is not None:
                    position = occurrence_end

    if not citations:
        # A CFR-shaped whole value whose title is outside the CFR's series but
        # whose numbers are a real Register volume and page reads as the FR
        # citation it is: the text's own numbers refute its claimed scheme.
        # Whole-value only, and only where the CFR reading is IMPOSSIBLE — a
        # title the CFR actually has is never second-guessed.
        relabel = _CFR_TITLE_IMPOSSIBLE_IS_FR.match(normalized)
        if relabel is not None:
            volume, page = int(relabel.group("volume")), int(relabel.group("page"))
            if (
                not _cfr_title_is_possible(volume)
                and 1 <= volume <= FR_VOLUME_HIGHEST_KNOWN
                and 1 <= page <= FR_PAGE_HIGHEST_KNOWN
            ):
                return (
                    AuthorityCitation(
                        authority_type="federal_register",
                        parse_status="partial",
                        fr_volume=volume,
                        fr_page=page,
                    ),
                )
        bare_usc = (
            _BARE_USC_TITLE.match(normalized)
            or _BARE_USC_TITLE_LONGHAND.match(normalized)
            or _USC_TITLE_WITH_DESIGNATOR.match(normalized)
        )
        if bare_usc is not None:
            # "16 USC et seq" names a title wholesale. Partial, never "ok":
            # a title without a section identifies a body of law, not a
            # provision — the same posture as the part-less CFR read.
            citation = AuthorityCitation(
                authority_type="usc",
                parse_status="partial",
                usc_title=int(bare_usc.group("title")),
            )
            _add(citation, bare_usc)
            return (citation,)
        if usc_record is not None:
            # Locating occurrences discards the whole-value row, and naming an
            # act over a whole document walks back from every "Act" in it.
            return ()
        # A row nothing could resolve still carries what it states. Partial
        # information is worth keeping: a consumer looking for section 326 of
        # an NDAA can find the row even where no reader can say which year's
        # NDAA it is. These are statements, never resolutions -- act_key stays
        # NULL, and nothing downstream may treat a stated name as an identity.
        # The ORIGINAL text is read, not the repaired one: a value states what
        # its publisher wrote.
        return (
            AuthorityCitation(
                authority_type="other",
                parse_status="failed",
                stated_act_name=stated_act_name(text),
                stated_section=stated_section(text),
            ),
        )
    if len(citations) > 1:
        # Several citations can each cover the whole string only vacuously;
        # one string, several authorities means none of them is the whole.
        citations = [replace(item, parse_status="partial") for item in citations]
    return tuple(citations)


# --------------------------------------------------------------------------- #
# Act-relative citations — the grammar half; resolution lives in
# refspec.registry.act_resolution over the pinned OLRC artifacts.

#: "sec. 111", "section 111", "§ 111" — the marker an act-relative citation
#: hangs its section on.
_ACT_SECTION = re.compile(r"(?:sec(?:tion)?s?\.?|§{1,2})\s*(?P<section>\d+[A-Za-z]?)", re.IGNORECASE)
_CITED_DIVISION = re.compile(r"(?i:\bdiv(?:ision)?\.?)\s+(?P<division>[A-Z]{1,3})\b")
#: The inverted spelling: "sec. 3505 of the Modernization of Cosmetics ... Act",
#: and its comma form "Sec 13(a)(15), Fair Labor Standards Act" (25 failed
#: values, measured 2026-08-21).
_ACT_SECTION_OF_THE = re.compile(r"\s*(?:of\s+(?:the\s+)?|,\s*(?:the\s+)?|\s+)", re.IGNORECASE)
_ACT_SPACE = re.compile(r"\s*")
_ACT_PARENTHETICAL = re.compile(r"\([^()]{1,12}\)")
_ACT_DIVISION_OF = re.compile(r"\s+of\s+(?:the\s+)?", re.IGNORECASE)
_ACT_NAME_GAP = re.compile(r"[\s,:\"'”’)]*")
#: No popular name in the Popular Name Tool is longer than this many words;
#: bounding the backward scan keeps recognition linear in the text.
_MAX_ACT_NAME_WORDS = 24
#: Punctuation a name may pick up from the sentence around it.
_NAME_EDGE = re.compile(r"^[\s(\"'“”]+|[\s,;:.)\"'“”]+$")
_CURLY_APOSTROPHE = re.compile(r"[’‘`]")


def normalize_popular_name(name: object) -> str:
    """The key a popular name joins on.

    Case, whitespace, sentence punctuation and the difference between a curly
    and a straight apostrophe are all spelling, not identity: the Popular Name
    Tool writes "Workers’ Compensation Act" and prose writes "Workers'
    Compensation Act", and they are one act. Internal commas are kept, because
    "Federal Food, Drug, and Cosmetic Act" is how that act is named.

    **Straightening runs before edge-stripping, and the order is the point.**
    OLRC writes four names with TeX quotes — ``` ``SPARS'' Act ``` — whose
    opening pair is two backticks. :data:`_NAME_EDGE` does not recognize a
    backtick as edge punctuation, so stripping first left the opening pair
    standing, and straightening then turned it into ``''spars'' act`` — a key
    this very function strips the front off, so no query could ever spell it.
    Straightening first makes the function idempotent on all four, which is
    what a join key has to be: ``normalize(normalize(x)) == normalize(x)``,
    pinned by ``test_a_normalized_name_is_a_fixed_point``. Measured over the
    20,865 rows of the pinned popular-name table, the order changes the answer
    for exactly those four names and nothing else.
    """

    text = _CURLY_APOSTROPHE.sub("'", _normalize_dashes(str(name or "")))
    text = _NAME_EDGE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


_YEAR_PREFIXED_NAME = re.compile(r"^\s*(?:the\s+)?((?:18|19|20)\d{2})\s+(\S.*)$", re.IGNORECASE)


def act_name_with_trailing_year(name: str) -> str | None:
    """A candidate spelling, admitted only by the caller's existing name index.

    Shared with Unified Agenda prose recovery: '2020 PIPES Act' ->
    'PIPES Act of 2020'. This reorders a stated year; it supplies none.
    """
    match = _YEAR_PREFIXED_NAME.match(name)
    return f"{match.group(2)} of {match.group(1)}" if match else None


@dataclass(frozen=True)
class ActRelativeCitation:
    """A provision cited through the act that created it.

    "Clean Air Act section 111" identifies a real provision but names no code,
    title or section number — it resolves only through the OLRC's tables, so
    this type carries what the text said and nothing it did not.
    """

    act_name: str
    act_key: str
    section: str
    #: The division the citation itself names, when it names one. ``None``
    #: means the text stated none — never that it stated the whole law.
    division: str | None = None


@dataclass(frozen=True)
class ActRelativeCitationOccurrence:
    """An exact act-section mention; its labels are not mapped USC subsections."""

    citation: ActRelativeCitation
    start: int
    end: int
    text: str
    pinpoint: tuple[str, ...] = ()


def _act_name_span(
    document: str, words: list[re.Match[str]], act_names: Container[str], *, before: bool
) -> tuple[int, int, str, str] | None:
    """Longest indexed name from at most 24 adjacent source tokens."""
    for length in range(len(words), 0, -1):
        selected = words[-length:] if before else words[:length]
        start, end = selected[0].start(), selected[-1].end()
        raw = document[start:end]
        if _CITATION_PARAGRAPH_BREAK.search(raw):
            continue
        candidate = " ".join(raw.split())
        key = normalize_popular_name(candidate)
        if key not in act_names:
            reordered = act_name_with_trailing_year(key)
            if reordered is None or reordered not in act_names:
                continue
            key = reordered
        edges = list(_NAME_EDGE.finditer(raw))
        left = edges[0].end() if edges and edges[0].start() == 0 else 0
        right = edges[-1].start() if edges and edges[-1].end() == len(raw) else len(raw)
        return start + left, start + right, _NAME_EDGE.sub("", candidate), key
    return None


def find_act_relative_occurrences(
    text: object, *, act_names: Container[str]
) -> tuple[ActRelativeCitationOccurrence, ...]:
    """Read indexed act names with exact spans, repeats and source pinpoints.

    The supplied name index remains the grammar: no guessed acronyms or acts.
    Tokens are indexed once; each section examines at most 24 adjacent tokens
    on either side instead of splitting the entire preceding document again.
    A directly adjacent name is supported by the published 199510 crop-insurance
    authority fields. A division must explicitly name the act it belongs to;
    nearby prose is never searched for a replacement division.
    """
    document = "" if text is None else str(text)
    words = list(re.finditer(r"\S+", document))
    starts, ends = [w.start() for w in words], [w.end() for w in words]
    found: list[ActRelativeCitationOccurrence] = []
    for marker in _ACT_SECTION.finditer(document):
        section = _usc_section(marker.group("section"))
        if section is None:
            continue
        end, labels = marker.end(), []
        while True:
            position = _ACT_SPACE.match(document, end).end()
            if _CITATION_PARAGRAPH_BREAK.search(document, end, position):
                break
            parenthetical = _ACT_PARENTHETICAL.match(document, position)
            if parenthetical is None:
                break
            label = _CFR_PINPOINT_LABEL.fullmatch(document, position, parenthetical.end())
            if label is not None and not (position > end and label.group(1).isdigit() and len(label.group(1)) == 4):
                labels.append(label.group(1))
            end = parenthetical.end()  # Other short qualifiers remain in the exact source slice.
        left = bisect_right(ends, marker.start())
        named = _act_name_span(document, words[max(0, left - _MAX_ACT_NAME_WORDS) : left], act_names, before=True)
        if named is not None and (
            not _ACT_NAME_GAP.fullmatch(document, named[1], marker.start())
            or _CITATION_PARAGRAPH_BREAK.search(document, named[1], marker.start())
        ):
            named = None
        if named is None:
            opening = _ACT_SECTION_OF_THE.match(document, end)
            if opening is None or _CITATION_PARAGRAPH_BREAK.search(document, end, opening.end()):
                continue
            right = bisect_left(starts, opening.end())
            named = _act_name_span(document, words[right : right + _MAX_ACT_NAME_WORDS], act_names, before=False)
        if named is None:
            continue
        name_start, name_end, name, key = named
        start, end = min(marker.start(), name_start), max(end, name_end)
        division = None
        if name_start == start:
            prefix = words[max(0, bisect_right(ends, start) - 4)].start()  # "division B of the"
            for stated in _CITED_DIVISION.finditer(document, prefix, start):
                if _ACT_DIVISION_OF.fullmatch(document, stated.end(), start):
                    division, start = stated.group("division"), stated.start()
                    break
        if isinstance(act_names, Mapping):
            key = act_names[key]  # Preserve the supplied canonical spelling map.
        citation = ActRelativeCitation(name, key, section, division)
        found.append(ActRelativeCitationOccurrence(citation, start, end, document[start:end], tuple(labels)))
    return tuple(found)


def find_act_relative_citations(text: object, *, act_names: Container[str]) -> tuple[ActRelativeCitation, ...]:
    """Identity-only view of the same matcher, deduplicated in source order."""
    return tuple(dict.fromkeys(item.citation for item in find_act_relative_occurrences(text, act_names=act_names)))


@dataclass(frozen=True)
class FederalRegisterCitation:
    """One "VV FR PPPPP" citation: a volume and starting page."""

    volume: int
    page: int


#: A Supreme Court opinion's citation column carries two schemes. A bound
#: opinion states its U.S. Reports citation ("608 U.S. 32"); a slip opinion
#: is not in a bound volume yet, so the same column states where it will
#: appear -- the preliminary print volume and part ("608/2"). The second is a
#: publication location, not an opinion identity: one part holds many
#: opinions, so sixteen slip opinions share "608/2". Reading them as one
#: scheme collides them; the discriminator is the publisher's own filename,
#: where a bound opinion is served as "608us1r32_*.pdf" and a slip opinion as
#: "24-43_*.pdf".
_US_REPORTS_CITATION = re.compile(r"^\s*(?P<volume>\d{1,4})\s*U\.?\s*S\.?\s*(?P<page>\d{1,4})\s*$")
_PRELIMINARY_PRINT_LOCATOR = re.compile(r"^\s*(?P<volume>\d{1,4})\s*/\s*(?P<part>\d{1,2})\s*$")
_BOUND_OPINION_FILENAME = re.compile(r"/\d+us\d+")


@dataclass(frozen=True, slots=True)
class SupremeCourtCitation:
    """What one opinion's citation column states, and under which scheme."""

    scheme: str
    us_reports_volume: int | None = None
    us_reports_page: int | None = None
    preliminary_print_volume: int | None = None
    preliminary_print_part: int | None = None


#: The words an act's name may carry between its capitalized parts. Anything
#: else ends the name walking backwards, which is what keeps
#: "5 USC (Ethics in Government Act of 1978)" from reading as the fragment
#: "Government Act of 1978".
#:
#: "&" is one of them because the corpus writes it where a name says "and" --
#: "Immigration & Nationality Act", "Omnibus Crime Control & Safe Streets Act"
#: -- and the spelling closure over the OLRC index already treats the two as
#: one spelling. Until 2026-08-24 a bare ampersand ended the walk, so those
#: names were reported as their tails ("Nationality Act", "Safe Streets Act").
_ACT_NAME_CONNECTORS = frozenset({"of", "for", "and", "the", "to", "on", "in", "with", "&"})
#: Walking backwards, a name is made of capitalized words only. A year is
#: never picked up here -- it is read from the trailing "of 1978" instead --
#: because allowing bare digits let a section number into the name:
#: "42 USC 7401 Clean Air Act" read as "USC 7401 Clean Air Act".
_ACT_NAME_TOKEN = re.compile(r"[A-Z][\w'\-&]*")
#: One word walking backwards, with the ABBREVIATION MARK the corpus writes
#: inside act names: "International Security & Development Coop. Act of 1981"
#: (0420-AA10, 15 rows), "Rehab. Act of 1973", "Magnuson Fishery Conservation &
#: Mgmt. Act", "Juvenile Justice & Delinquency Prev. Act of 1974". Until
#: 2026-08-24 the grab was ``[\w'\-&]+$``, which cannot end on a period, so the
#: walk stopped dead at the abbreviation and those values stated NO name at all
#: -- review #2 traced the Coop. case (notes/G.json). It is also what truncated
#: a middle initial: "Richard B. Russell National School Lunch Act" was
#: reported as "Russell National School Lunch Act".
#:
#: The period is a mark on the word, not part of it, so every test the walk
#: makes -- stop token, capitalization, connector, designator -- is made
#: against the word with the mark removed.
_ACT_NAME_WORD = re.compile(r"[\w'\-&]+\.?$")
#: Tokens that end the walk however capitalized they are: a citation scheme
#: is the thing beside the name, never part of it.
#: A single letter or Roman numeral leading a name is a division or title
#: designator that the surrounding prose numbers, not part of the name.
_ACT_NAME_DESIGNATOR = re.compile(r"[A-Z]|[IVXLC]{1,5}")
_ACT_NAME_STOP_TOKENS = frozenset(
    {"USC", "USCA", "CFR", "STAT", "FR", "PL", "EO", "APP", "SEC", "SECS", "SECTION", "PUB", "L"}
)
#: An act's name may continue PAST the word "Act", and the walk is backwards,
#: so the tail is read forwards in two steps.
#:
#: The Amendments are a different act, not a longer way of saying the same
#: one. All four of these are entries in the OLRC's own Popular Name Tool,
#: distinct from their base acts: Clean Air Act Amendments of 1990,
#: Rehabilitation Act Amendments of 1992, Single Audit Act Amendments of
#: 1996, Lacey Act Amendments of 1981 — and for the last three the BASE name
#: is not an index entry at all, so a reader stopping at "Act" reported a
#: name that names nothing. 72 distinct Agenda values, 311 rows.
#:
#: Capitalized only, per this module's capitalization-as-evidence rule:
#: "Section 320 of the 1990 Clean Air Act amendments" (5 values, 20 rows) is
#: prose ABOUT the act, and the amending act's own name is not what it wrote.
_ACT_NAME_AMENDMENTS = re.compile(r"\s+Amendments?\b")
#: A trailing year, however the publisher punctuates it — "of 1978", ", 1978",
#: " 1978" all name the same year, and the name is published with "of".
_ACT_NAME_YEAR = re.compile(r"\s*(?:,\s*)?(?:of\s+)?(?P<year>1[7-9]\d\d|20\d\d)\b")
#: One piece of a stated section: digits, a letter run, or digits with a
#: letter suffix — and the letters are ONE LETTER REPEATED, carrying their own
#: right edge, exactly as :data:`_USC_SECTION_TOKEN` spells the same rule for
#: the Code. Acts number their sections every way there is ("4.14B",
#: "1860D-31", "1861(v)(1)(A)", division "N"), so the pieces join over "." and
#: "-" and the parenthesised tail is kept.
#:
#: What the repetition rule refuses is a word whose space was lost. The
#: capture was ``[\w.\-]*`` before, which took whatever followed:
#: "PL 103-66, sec 6002Omnibus Budget Reconciliation Act of 1993" stated a
#: section named "6002Omnibus", and "Sec 123BBRA 1999" one named "123BBRA".
#: Measured over all 1,974 distinct ``stated_section`` values the pinned
#: table carries (28,321 rows), exactly FOUR contain a letter run of two
#: different letters and all four are this damage — "6002Omnibus" (6 rows),
#: "123BBRA", "301as" (from "301 as amended") and "501to". The letters stay
#: uncovered text, so nothing vanishes and the digits in front are still read.
_STATED_SECTION_PIECE = rf"(?:\d+(?:{_ONE_REPEATED_LETTER}(?![A-Za-z]))?|{_ONE_REPEATED_LETTER}(?![A-Za-z]))"

#: The one reader whose section capture admits a LETTER, and so the one the
#: marker's right-hand boundary actually protects: everywhere else a digit is
#: required after the marker, which refused a sliced word by accident. Its
#: own spelling of the marker was a fourth, narrower copy -- it could not
#: read "sections" at all, taking the plural's "s" as the section number --
#: so it now uses the shared one.
_STATED_SECTION = re.compile(
    rf"\b{_SECTION_MARKER}\s*"
    rf"(?P<section>{_STATED_SECTION_PIECE}(?:[.\-]{_STATED_SECTION_PIECE})*(?:\([\w]+\))*)",
    re.IGNORECASE,
)


def stated_act_name(text: str) -> str | None:
    """The act name a value states, whole, or ``None``.

    This is a STATEMENT, never a resolution: it reports the name as written
    without claiming to know which act that is. "Sec 326, National Defense
    Authorization Act" states an act family and a section while naming no
    particular year's NDAA, and there is one nearly every year -- so the name
    is worth carrying and the identity is not.

    The name is read by walking backwards from the word "Act" over
    capitalized tokens and the connectors between them, so a name is either
    captured whole or not at all -- and then FORWARDS over the tail the name
    may carry past that word: "Amendments", and a year. Both halves matter to
    identity, because "Clean Air Act Amendments of 1990" is a different act
    from the Clean Air Act, with its own entry in the OLRC's index.

    What the walk reports is the publisher's own SPAN, sliced from the value
    between the first token it kept and the word "Act" -- not the tokens
    rejoined with single spaces. The two agree on every one of this corpus's
    42,677 distinct values today, and they stop agreeing the moment a word
    carries an abbreviation mark: "U.S." is two tokens with no space between
    them, and rejoining them writes "U. S.", a spelling no filer used.
    """

    normalized = _normalize_dashes(text)
    best: str | None = None
    for match in re.finditer(r"\bActs?\b", normalized):
        head = normalized[: match.start()].rstrip()
        # (word without its abbreviation mark, where the word begins).
        tokens: list[tuple[str, int]] = []
        while head:
            token = _ACT_NAME_WORD.search(head)
            if token is None:
                break
            word = token.group(0).rstrip(".")
            if word.upper() in _ACT_NAME_STOP_TOKENS:
                break
            if _ACT_NAME_TOKEN.fullmatch(word) or word.lower() in _ACT_NAME_CONNECTORS:
                tokens.append((word, token.start()))
                head = head[: token.start()].rstrip()
                continue
            break
        while tokens and tokens[-1][0].lower() in _ACT_NAME_CONNECTORS:
            tokens.pop()
        # A name never opens on a bare designator. "division F of the National
        # Defense Authorization Act" names the NDAA; the F is where in it.
        while tokens and _ACT_NAME_DESIGNATOR.fullmatch(tokens[-1][0]):
            tokens.pop()
            while tokens and tokens[-1][0].lower() in _ACT_NAME_CONNECTORS:
                tokens.pop()
        if not tokens or not any(_ACT_NAME_TOKEN.fullmatch(word) and word[:1].isupper() for word, _ in tokens):
            continue
        name = normalized[tokens[-1][1] : match.end()]
        # Forwards over the tail, in the order the publisher writes it: the
        # amending act's own word, then the year that distinguishes one year's
        # amendments from another's.
        cursor = match.end()
        amendments = _ACT_NAME_AMENDMENTS.match(normalized, cursor)
        if amendments is not None:
            name = f"{name} {amendments.group(0).strip()}"
            cursor = amendments.end()
        year = _ACT_NAME_YEAR.match(normalized, cursor)
        if year is not None:
            name = f"{name} of {year.group('year')}"
        if best is None or len(name) > len(best):
            best = name
    return best


def stated_section(text: str) -> str | None:
    """The section number a value states behind a section marker, or ``None``.

    A marker is what makes it a statement rather than a guess: "1921 et seq."
    states no section, while "ANILCA sec 203" states section 203 of an act
    this reader cannot name.
    """

    match = _STATED_SECTION.search(_normalize_dashes(text))
    return match.group("section") if match is not None else None


def parse_supreme_court_citation(citation: object, source_url: object) -> SupremeCourtCitation:
    """Read a citation under the scheme its own source URL declares.

    The URL is the discriminator, not a heuristic over the citation text: the
    publisher serves a bound opinion from a volume-paginated filename and a
    slip opinion from a docket-numbered one. A citation whose shape disagrees
    with its URL is left unread rather than forced into either scheme.
    """

    text = "" if citation is None else str(citation).strip()
    url = "" if source_url is None else str(source_url)
    bound = _BOUND_OPINION_FILENAME.search(url) is not None
    if bound:
        match = _US_REPORTS_CITATION.match(text)
        if match is None:
            return SupremeCourtCitation(scheme="unread")
        return SupremeCourtCitation(
            scheme="us_reports",
            us_reports_volume=int(match.group("volume")),
            us_reports_page=int(match.group("page")),
        )
    match = _PRELIMINARY_PRINT_LOCATOR.match(text)
    if match is None:
        return SupremeCourtCitation(scheme="unread")
    return SupremeCourtCitation(
        scheme="preliminary_print",
        preliminary_print_volume=int(match.group("volume")),
        preliminary_print_part=int(match.group("part")),
    )


@dataclass(frozen=True)
class FederalRegisterCitationOccurrence:
    """A Federal Register citation with its exact, codepoint-indexed source slice."""

    citation: FederalRegisterCitation
    start: int
    end: int
    text: str


def find_federal_register_citations(text: str) -> tuple[FederalRegisterCitationOccurrence, ...]:
    """Every Federal Register citation in one string, in order, with where it was read.

    The Unified Agenda's timetable field writes these as the whole value
    ("89 FR 91529"); prose writes them inline. Uppercase "FR" is required —
    lowercase is ordinary prose, the same capitalization-as-evidence rule the
    bare "EO" and "Stat" forms carry. The match runs over the dash-folded
    text, one character for one, so spans index ``text`` itself.
    """

    normalized = _normalize_dashes(text)
    return tuple(
        # The page reads through leading zeros ("62 FR 04670" occurs in the
        # Agenda's own field) by integer value — the third appearance of the
        # zero-padding lesson today. Page 0 does not exist and stays unread.
        FederalRegisterCitationOccurrence(
            FederalRegisterCitation(volume=int(m.group("volume")), page=page),
            m.start(),
            m.end(),
            text[m.start() : m.end()],
        )
        for m in _FR_CITATION_FORM.finditer(normalized)
        if (page := int(m.group("page").replace(",", ""))) > 0
    )


def parse_federal_register_citations(text: str) -> tuple[FederalRegisterCitation, ...]:
    """Every Federal Register citation in one string, in order: :func:`find_federal_register_citations` without spans."""

    return tuple(occurrence.citation for occurrence in find_federal_register_citations(text))


# --------------------------------------------------------------------------- #
# The Unified Agenda's timetable FR_CITATION column
#
# This column declares its own scheme, which is why a reader for it can say
# things a prose grammar may not — the same licence
# :func:`parse_supreme_court_citation` takes from a publisher's filename.
# Everything below reads values the FR grammar above CANNOT read, so it never
# offers a second answer for a value that already has one.
#
# What is here is what the TEXT decides, plus the row's own ``rin``. Two
# further rules from the same census are deliberately NOT here because they
# are not text: the sibling-edition oracle (join the same RIN, action and date
# across the 60 pinned editions; it answers 9 rows, uniquely in every one) and
# the Federal Register API. Both belong to a builder that holds the corpus.


#: A named damage operator's cost, in the one metric that names the operators
#: this publisher actually commits: insertion, deletion, substitution, and
#: TRANSPOSITION. The last is what makes this Damerau rather than plain
#: Levenshtein, and it is not academic — "74 RF 31642" is the label
#: transposed, and plain edit distance would price it at two.
def damerau_levenshtein(left: str, right: str) -> int:
    """How many named single-character operations separate two strings.

    Written here rather than depended on because it IS the vocabulary this
    module argues in: every repair in :data:`_WHOLE_VALUE_LABEL_REPAIRS` is
    one of these four operations on a label, and a fence stated as a distance
    can be checked, where an enumerated set can only be extended.
    """

    seen: dict[str, int] = {}
    far = len(left) + len(right)
    grid = [[far] * (len(right) + 2) for _ in range(len(left) + 2)]
    for i in range(len(left) + 1):
        grid[i + 1][1] = i
    for j in range(len(right) + 1):
        grid[1][j + 1] = j
    for i in range(1, len(left) + 1):
        last_match_column = 0
        for j in range(1, len(right) + 1):
            last_match_row = seen.get(right[j - 1], 0)
            # Captured BEFORE the match below may advance it: the transposition
            # term is priced against the PREVIOUS match, and reading the
            # updated column here makes the metric too cheap ("FRFR" to "FR"
            # priced at 1, where two deletions are the only route).
            swap_column = last_match_column
            cost = 0 if left[i - 1] == right[j - 1] else 1
            if not cost:
                last_match_column = j
            grid[i + 1][j + 1] = min(
                grid[i][j] + cost,  # substitution
                grid[i + 1][j] + 1,  # insertion
                grid[i][j + 1] + 1,  # deletion
                grid[last_match_row][swap_column]  # transposition
                + (i - last_match_row - 1)
                + 1
                + (j - swap_column - 1),
            )
        seen[left[i - 1]] = i
    return grid[len(left) + 1][len(right) + 1]


#: How far a damaged "FR" label may sit from the real one before a positional
#: reading is refused. ONE, and the bound is bought by a negative result.
#:
#: The whole residue space of the column is 18 values, measured over all
#: 671,959 rows. Widening an enumerated set to DL <= 1 admits 91 rows by
#: residue, but 85 of them ("CFR" 64 relabeled, "-FR" 16 ok, "FR-" 5 ok) are
#: consumed by an earlier branch and never reach a positional reading; the 6
#: whose status actually changes ("FRX" x3, "DR", "FSR", "NFR") are each
#: independently corroborated, with zero overfire.
#:
#: DL <= 2 admits four more and is WRONG on all four, invisibly: "70 FR AT97"
#: -> 70 FR 97, "72 FR AU91" -> 72 FR 91, "83 FR AK07" -> 83 FR 7, "90-21215"
#: -> 90 FR 21215. Every one of those pages really exists, so no range check
#: catches the error. The fence holds NOT because the operators past it are
#: unnameable — insertion and substitution are as ordinary as the deletion and
#: transposition inside it — but because the second number in those four
#: values is not a page at all: in three it is the digits inside the RIN's own
#: suffix, and in the fourth a document-number sequence.
FR_LABEL_MAX_EDITS = 1


@dataclass(frozen=True, slots=True)
class TimetableFrCitation:
    """What one timetable value states, and under which scheme.

    ``scheme`` names the reading OR the refusal, because a value that carries
    no page is a different fact from a value nothing could read, and the
    census has five of the first kind and one of the second.
    """

    scheme: str
    volume: int | None = None
    page: int | None = None
    #: An FR document number ("2025-21215"), where the value names one instead
    #: of a page. The page it resolves to is the Register's to say.
    fr_document_number: str | None = None


#: NARA writes "<volume>-<issue>; <first page>-<last page>". Three Direct
#: Final Rules in edition 202410, every field verified four ways (govinfo
#: issue metadata for the volume and issue, the FR API keyed on the row's own
#: RIN for both page ends, and the row's own date): "89-61; 21436-21437" is
#: Vol. 89 No. 61, pages 21436-21437, RIN 3095-AC17, published 2024-03-28.
#: No damage operator is involved — the value is complete and correct under a
#: grammar the reader did not know, and "89 FR 21436" is DERIVABLE from it.
#: The space before the semicolon is the publisher's ("89-105 ; 46803-46805").
#: Measured over all 671,959 rows: 3 matches, all currently failed.
_NARA_ISSUE_CITATION = re.compile(
    r"^\s*(?P<volume>[1-9]\d{0,2})\s*-\s*(?P<issue>[1-9]\d{0,3})\s*;\s*"
    r"(?P<page>[1-9]\d{0,5})\s*-\s*(?P<page_end>[1-9]\d{0,5})\s*$"
)

#: "90-21215" — a volume and a Federal Register DOCUMENT number's sequence
#: half, which is why it is told apart from the NARA form by punctuation and
#: not by its numbers: NARA carries a semicolon and a page range, and an FR
#: volume has roughly 250 issues, so a five-digit second number is no issue.
#: Measured over all 671,959 rows: 1 match, and it is failed.
_FR_DOCUMENT_NUMBER = re.compile(r"^\s*(?P<volume>[1-9]\d{0,2})\s*-\s*(?P<sequence>\d{1,6})\s*$")

#: A value that stops after the label ("71 FR"), or whose page is all zeros
#: ("86 FR 00000" — five zeros, exactly the width of an FR page, a template
#: placeholder written before the OFR assigned one). Six rows, all failed.
_FR_VOLUME_WITHOUT_PAGE = re.compile(r"^\s*(?P<volume>[1-9]\d{0,2})\s*(?:FR|F\.\s?R\.)\s*0*\s*$", re.IGNORECASE)

#: The page slot, whatever is in it, once the volume and label are taken off.
_FR_PAGE_SLOT = re.compile(r"^\s*(?P<volume>[1-9]\d{0,2})\s*(?:FR|F\.\s?R\.)\s*(?P<slot>\S+)\s*$", re.IGNORECASE)

#: Volume 1 of the Federal Register is 1936, so a volume names its year.
_FR_VOLUME_EPOCH = 1935


def parse_agenda_timetable_citation(text: str, *, rin: str | None = None) -> TimetableFrCitation:
    """Read a timetable value the Federal Register grammar could not read.

    The column declares the scheme, so this reader may use conventions a prose
    grammar may not — and it NAMES every reading and every refusal, because
    "the publisher stated no page" and "nothing here could be read" are
    different facts that a single ``failed`` bucket hides.

    ``rin`` is a discriminator, not a hint: three values carry the row's own
    RIN suffix where the page belongs ("0648-AT97" -> "70 FR AT97"), which is
    checkable against that column and against nothing else. Without the RIN
    the claim cannot be made, so it is not made.

    Returns ``scheme="unread"`` for anything else, including the ordinary
    "89 FR 91529" — that form has a reader already, and a second answer for a
    value that has one is worse than no answer.
    """

    normalized = _normalize_dashes(text or "")

    nara = _NARA_ISSUE_CITATION.match(normalized)
    if nara is not None:
        return TimetableFrCitation(scheme="nara-issue", volume=int(nara.group("volume")), page=int(nara.group("page")))

    # Before the bare volume-and-sequence form, because "89-61; 21436-21437"
    # would not reach here anyway and the order should say which is narrower.
    document = _FR_DOCUMENT_NUMBER.match(normalized)
    if document is not None:
        volume = int(document.group("volume"))
        if 1 <= volume <= FR_VOLUME_HIGHEST_KNOWN:
            # The page is the Register's to say. Volume-to-year is a bijection
            # and that is ALL the text yields; the positional reading is not
            # merely unsupported but refuted (90 FR 21215 is the first page of
            # the issue of 2025-05-19, six months before this row's own date,
            # on a day its agency published nothing).
            return TimetableFrCitation(
                scheme="fr-document-number",
                volume=volume,
                fr_document_number=f"{volume + _FR_VOLUME_EPOCH}-{document.group('sequence')}",
            )

    volume_only = _FR_VOLUME_WITHOUT_PAGE.match(normalized)
    if volume_only is not None:
        return TimetableFrCitation(scheme="page-unstated", volume=int(volume_only.group("volume")))

    slot = _FR_PAGE_SLOT.match(normalized)
    if slot is not None and rin:
        suffix = str(rin).split("-")[-1].strip().upper()
        if suffix and slot.group("slot").upper() == suffix:
            # Reading these as pages produces three real, wrong pages — 70 FR
            # 97, 72 FR 91 and 83 FR 7 all exist in the opening days of their
            # volumes — so a range check would never catch it. The page was
            # never written; this is a label, not a parse.
            return TimetableFrCitation(scheme="page-is-the-rin-suffix", volume=int(slot.group("volume")))

    return TimetableFrCitation(scheme="unread")
