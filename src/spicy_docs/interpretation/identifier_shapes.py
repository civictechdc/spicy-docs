"""Catalog identifier shapes: RIN, Federal Register documents, dockets.

The citation grammars (CFR, U.S.C., public laws, executive orders, Statutes at
Large) live in :mod:`spicy_docs.interpretation.citation_grammar`. This module owns the
other half of what SpicySearch's ``identifiers.py`` knew: the shapes of the
*catalog* identifiers — the strings that name a rulemaking, a Federal Register
document, or a docket — plus the validators and normalizers both sides of
every join must share, and the overlap sweep that arbitrates when two grammars
claim the same characters.

Provenance: ported from SpicySearch ``identifiers.py`` and the ``citations.py``
lineage's normalizers, each rule carrying the measurement that bought it. What
is deliberately NOT here: SpicySearch's exact-catalog query policy stays in
SpicySearch — "is this string a query for an identifier" is a search decision,
not a shape fact.

IRI minting is no longer among them. This header said minting "stays with
consumers until the minting layer is its own port" until 2026-09-04; that port
landed on 2026-08-31 in `582461fe`, and :mod:`refspec.registry.iri_minting`
quotes this very sentence as the hole it fills. Two modules asserting opposite
things about the same boundary is worse than either being wrong alone, so the
claim is retired here rather than softened. Minting reads this module's shapes
and lives next door.

Two readers, two questions
--------------------------
Everything below serves one of two readers, and confusing them is how this
module goes wrong:

- the **prose reader** (:func:`detect_identifier_shapes`) is handed running
  text and must decide where an identifier begins and ends. Every extra thing
  it will admit is a false positive waiting in an unrelated sentence, so its
  grammar is deliberately narrow.
- the **column reader** (:func:`normalize_docket_reference` and friends) is
  handed one field whose *name* already declares what it holds. It can afford
  shapes the prose reader must refuse, because the column is the license.

Where they disagree, the disagreement is stated and measured. Where they read
the same convention — the docket label, the mintable document-number space —
that convention is written once and both read it, because the two spellings
drifting apart is the defect this module keeps producing.

The load-bearing lessons, so they are not simplified away
--------------------------------------------------------

- **Validators answer "is this string one", never "does it contain one."**
  56,364 of 64,537 catalog docket ``rin`` values are the literal string
  "Not Assigned"; admitted by a containment test it became the corpus's most
  common identifier by a factor of ten.
- **A docket's organization token opens on a letter.** That is the whole
  difference between reading "DHS Docket No. USCIS-2025-0004" and turning
  "MM Docket No. 98-213" into docket "98-213": a remainder that opens on a
  number is what the label was numbering. Measured on a full revision
  candidate: requiring the shape refuses 5,214 of 5,506 mutilated references
  and costs no real docket.
- **A label licenses the two-digit-year form for the prose reader.** Labeled
  "AMS-SC-24-0046" is a docket; unlabeled in running text it is
  indistinguishable from a report number ("GAO-26-9060") and stays undetected
  rather than guessed. The column reader keeps the spelling, because the
  field is the license: 12,076 distinct references (17,284 occurrences) of
  the "AMS-SC-25-0848" form would otherwise be thrown away. The other
  two-digit-year family in that column is not kept as a docket at all — the
  24,548 FERC references of the "CP26-20-000" form belong to another
  registry, and :func:`numbering_system` names them instead.
- **Strip-then-validate, in that order only.** A value that is already a
  well-formed identifier is never label-stripped, so a docket whose
  organization is literally "DOCKET" cannot be mutilated by its own name.
- **A label is presentation, and only a whole word is a label.** Unbounded,
  "doc" ate the head of any word that started with it: "Document-2021-0317"
  minted docket UMENT-2021-0317. The unbounded spelling and the bounded one
  read 3,234 distinct references (4,819 occurrences) in the pinned docket
  column differently.

Measurements in this file are taken over four pinned columns, read
2026-08-22: the Unified Agenda's ``rin`` (46,547 distinct / 798,114
occurrences) and the Federal Register corpus's ``document_number``
(1,004,233 distinct), ``docket_ids_json`` (608,758 distinct / 893,824
occurrences) and ``regulation_id_numbers_json`` (36,563 distinct / 121,111
occurrences). The three numbers that come from somewhere else name where:
the SpicySearch catalog's own docket and document tables, and one full
revision candidate. A number with no corpus beside it is one of these four.

Provenance
----------
Moved into spicy-docs on 2026-09-23 beside :mod:`citation_grammar`, as the
stack's canonical identifier shapes (consolidation item B4 in
``docs/research/consolidation-path-2026-09-22.md``). The source is RefSpec
``src/refspec/registry/identifier_shapes.py`` at RefSpec ``4a680c81``,
unchanged since ``c9cc5410`` and so byte-identical to what the parsing survey
measured at ``f83c0d7a``. Two cross-references now name this package, the
layout is ``ruff format``'s, and :func:`unpadded_federal_register_document_number`
is new here; nothing else differs, and every RefSpec test that exercises this
module passed against this copy before it landed. Since the move this module
also hosts the Federal Register document-number spelling the joins share --
:func:`hyphenate_fr_doc_num`, :func:`fr_doc_num_mirror_series` and
:func:`fr_doc_num_release_spelling`, the one core the SEC comments join's
``normalize_fr_doc_num`` and :func:`unpadded_federal_register_document_number`
both delegate their mechanics to. The self-contained tests are
ported to ``tests/test_identifier_shapes.py``; the three that read RefSpec's
built artifacts stay beside them. ``refspec.registry.*`` names are RefSpec
modules that stay in RefSpec.
"""

from __future__ import annotations

import re
from collections.abc import Container, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER",
    "FEDERAL_REGISTER_DOCUMENT_NUMBER",
    "PUBLISHED_RIN",
    "IdentifierCandidate",
    "IdentifierKind",
    "NumberingSystem",
    "corrected_rin",
    "detect_identifier_shapes",
    "docket_reference_as_stated",
    "fr_doc_num_mirror_series",
    "fr_doc_num_release_spelling",
    "hyphenate_fr_doc_num",
    "is_federal_register_document_number",
    "is_regulation_identifier_number",
    "keep_longest_then_most_specific",
    "normalize_docket_reference",
    "normalize_docket_references",
    "normalize_regsgov_identifier",
    "normalize_rin",
    "numbering_system",
    "published_rin",
    "unpadded_federal_register_document_number",
]

# No identifier may start or end inside a longer token. The hyphen and
# underscore are part of the guard here (unlike the citation grammars'):
# catalog identifiers are hyphenated tokens, so a match must not begin or end
# mid-identifier.
_LEFT = r"(?<![A-Za-z0-9_-])"
_RIGHT = r"(?![A-Za-z0-9_-])"

#: Every dash spelling collapses to "-" before matching, one character for one
#: character, so spans on the normalized text still index the original.
#:
#: Deliberately shared, not module-private in spirit: :mod:`iri_minting` folds
#: dashes on the same values before minting them and imports this table
#: directly rather than keeping its own copy, because the two spellings
#: drifting apart is the defect this module's docstring names as its
#: recurring one. A leading underscore stays on the name -- nothing else in
#: this module's public surface carries one -- but the name is meant to be
#: reached from outside, and REF-052 is the ruling that retired the mirror
#: this comment used to warn a test to keep true.
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))


def _stated_text(value: object) -> str:
    """The characters a value states, stripped of surrounding whitespace.

    One coercion, so two readers cannot disagree about the same value. They
    did: ``str(value or "")`` made the falsy integer 0 state nothing while
    ``str(value)`` two functions away made it state "0". Only ``None`` states
    nothing.
    """

    return "" if value is None else str(value).strip()


def _folded_text(value: object) -> str:
    """The comparison form: dashes collapsed, letters uppercased.

    Folding is one character for one character, so a normalizer built on it
    can select and fold but never invent.
    """

    return _stated_text(value).translate(_DASHES).upper()


class IdentifierKind(StrEnum):
    """Kinds of catalog identifiers this module detects."""

    DOCKET = "docket"
    FEDERAL_REGISTER_DOCUMENT = "federal_register_document"
    REGULATIONS_GOV_DOCUMENT = "regulations_gov_document"
    RIN = "rin"


class NumberingSystem(StrEnum):
    """The numbering system a value announces itself as.

    A docket column is a mixed bag by construction: publishers put whatever
    number identifies their proceeding into it, and fifteen agency systems
    share the field with Regulations.gov dockets. Refusing all of them as
    "not a docket" throws away a fact the text already states -- the label IS
    the type declaration. "RELEASE NO. 33-8176" says what system it belongs
    to; nothing has to be inferred to record that.

    This classifies the system and stops there. Parsing a system's internals
    is a separate question needing its own oracle per family, and none of
    these is parsed here: an unrecognised label is ``None``, never a guess.
    """

    REGULATIONS_GOV_DOCKET = "regulations_gov_docket"
    FERC_DOCKET = "ferc_docket"
    AIRWORTHINESS_DIRECTIVE = "airworthiness_directive"
    AIRSPACE_DOCKET = "airspace_docket"
    AMENDMENT_NUMBER = "amendment_number"
    EPA_FEDERAL_REGISTER_LOCATOR = "epa_federal_register_locator"
    FILE_NUMBER = "file_number"
    OMB_CONTROL_NUMBER = "omb_control_number"
    PROJECT_NUMBER = "project_number"
    PUBLIC_NOTICE = "public_notice"
    RELEASE_NUMBER = "release_number"


#: The word an agency writes between a label and its number. One vocabulary,
#: read by the docket label below and by the numbering-system classifier, so
#: that "Docket Nos." and "File No." cannot mean one thing to one reader and
#: something else to the other. Spelled as a single optional-``s`` branch
#: rather than an alternation of singular and plural: written
#: ``no\.?|nos\.?`` the first branch wins on "Nos." and leaves a stray "s."
#: behind, which is exactly how references came to be mutilated: the two
#: spellings read 9,067 distinct references (12,970 occurrences) in the
#: pinned docket column differently.
#:
#: It ends at a word boundary or on its own period. Unfenced, it took the head
#: of the next word: "Docket NOAA-NOS-2024-0104" read as AA-NOS-2024-0104, and
#: a value opening "Notice-MVC-2015-01" or "NOP-13-01" as TICE-MVC-2015-01 and
#: P-13-01. The fence is at the word, not after the period, because the period
#: may abut the identifier: ``(?![A-Za-z])`` after ``no\.?`` was tried and
#: refuses "Docket No.CDC-2018-0075" (239 references in the pinned docket
#: column are written that way, 90 of them real dockets). Measured 2026-09-26
#: over the drift audit's inputs (receipt ``fork-execution-2026-09-21/
#: drift-qualification-2026-09-26/regulatory/d1d2-fix``, ``step-3``): the
#: single reader, ``numbering_system`` and the prose reader change no answer
#: over 1,170,347 docket values and 1,105,084 texts, and the plural reader
#: changes the four above, none a held docket before or after. A docket whose
#: organization IS a counter word ("NOS-…") would still lose it behind
#: "Docket"; no held docket has one.
_LABEL_COUNTER_WORD = r"(?:nos?(?:\.|\b)|numbers?\b|ids?\b)"

#: The punctuation an agency may put between the label and its number, and
#: which therefore belongs to neither.
_LABEL_PUNCTUATION = " #:.-"
_LEADING_COUNTER_WORD = re.compile(rf"^\s*{_LABEL_COUNTER_WORD}", re.IGNORECASE)

#: Each system is recognised by the label it states, anchored at the start of
#: the value, and only when something follows the label -- a bare "Docket No."
#: names no system. Two are named for their agency because the label is that
#: agency's own vocabulary and nothing else uses it: FRL is the identification
#: code EPA puts in a Federal Register document heading (40 CFR 23.1), and AD
#: is the FAA airworthiness directive whose three parts are year, biweekly
#: period, and sequence ("AD 2000-01-01"). The rest are named for what the
#: label says, not for the agency behind it, because "Release No." and
#: "File No." are ordinary words that more than one publisher could use.
#:
#: Each pattern matches the label and nothing else, and is applied with
#: ``match`` against an already-stripped value, which is the whole of what
#: "anchored at the start" means here. The airworthiness directive looks past
#: its punctuation to the first digit -- the digit is what distinguishes the
#: label from the two letters of an ordinary word -- but does not consume it,
#: so "what follows the label" means the same thing for all nine.
#:
#: Order is not load-bearing: each pattern opens on a different word, and no
#: value in the pinned columns matches two of them.
_NUMBERING_SYSTEM_LABELS: tuple[tuple[NumberingSystem, re.Pattern[str]], ...] = (
    (NumberingSystem.EPA_FEDERAL_REGISTER_LOCATOR, re.compile(r"FRL\b", re.IGNORECASE)),
    (NumberingSystem.OMB_CONTROL_NUMBER, re.compile(r"OMB\b", re.IGNORECASE)),
    (NumberingSystem.AIRWORTHINESS_DIRECTIVE, re.compile(r"AD\s*[#:]?(?=\s*\d)", re.IGNORECASE)),
    (NumberingSystem.AIRSPACE_DOCKET, re.compile(r"Airspace\b", re.IGNORECASE)),
    (NumberingSystem.RELEASE_NUMBER, re.compile(r"Release\b", re.IGNORECASE)),
    (NumberingSystem.FILE_NUMBER, re.compile(r"File\b", re.IGNORECASE)),
    (NumberingSystem.PUBLIC_NOTICE, re.compile(r"Public\s+Notice\b", re.IGNORECASE)),
    (NumberingSystem.PROJECT_NUMBER, re.compile(r"Project\b", re.IGNORECASE)),
    (NumberingSystem.AMENDMENT_NUMBER, re.compile(r"Amendment\b", re.IGNORECASE)),
)


def numbering_system(reference: object) -> NumberingSystem | None:
    """Which numbering system a reference announces itself as, or ``None``.

    A Regulations.gov docket answers first, whether stated bare or behind a
    label, because that is the system this registry can actually resolve.
    Every other answer comes from the value's own stated label: no system is
    ever inferred from bare digits, so "0741" is ``None`` while
    "Project 0741" is a project number.

    A label must *open* the value -- searched anywhere, every sentence
    mentioning a release would become a release number -- and something other
    than its own counter word must follow it. "File No." with nothing behind
    it is presentation with nothing to present; five such bare labels stand
    in the docket column and each used to be given a system.
    """

    if normalize_docket_reference(reference) is not None:
        return NumberingSystem.REGULATIONS_GOV_DOCKET
    # Before the label table: FERC's AD (administrative) and the FAA's AD
    # (airworthiness directive) share two letters, and the FERC form states
    # itself completely -- prefix, year, sequence, sub-docket -- while the
    # label table would answer from the letters alone.
    stated_reference = docket_reference_as_stated(reference)
    if stated_reference:
        for candidate in (stated_reference, _behind_the_docket_label(stated_reference)):
            if _FERC_DOCKET.fullmatch(_folded_text(candidate)):
                return NumberingSystem.FERC_DOCKET
    stated = docket_reference_as_stated(reference)
    if not stated:
        return None
    for system, label in _NUMBERING_SYSTEM_LABELS:
        match = label.match(stated)
        if match is None:
            continue
        numbered = _LEADING_COUNTER_WORD.sub("", stated[match.end() :], count=1)
        if numbered.strip(_LABEL_PUNCTUATION):
            return system
    return None


#: Which grammar wins when two claim exactly the same characters, most
#: specific first.
#:
#: The one contest the pinned columns actually produce is a Regulations.gov
#: document against the docket inside it, and it is an exact tie rather than
#: a containment: the docket grammar reads "EPA-HQ-OAR-2021-0317-0001" whole
#: by absorbing the year into the organization, so length cannot separate the
#: claims. 56 distinct docket references tie that way. No other pair of kinds
#: ties on any value in the four columns -- in particular a Federal Register
#: correction number produces no docket claim at all, because "C1" is one
#: letter where a docket organization needs two. The RIN and document
#: positions below therefore arbitrate nothing measured; they are here so the
#: order is total and the sort is deterministic.
_KIND_PRECEDENCE = (
    IdentifierKind.RIN,
    IdentifierKind.FEDERAL_REGISTER_DOCUMENT,
    IdentifierKind.REGULATIONS_GOV_DOCUMENT,
    IdentifierKind.DOCKET,
)


@dataclass(frozen=True, slots=True)
class IdentifierCandidate:
    """One identifier a text appears to name.

    ``span`` indexes the *original* text, so a caller can highlight or excise
    exactly what was read. ``value`` is the normalized surface form for exact
    comparison; ``components`` is the structure, and is authoritative wherever
    the two could disagree.
    """

    kind: IdentifierKind
    value: str
    span: tuple[int, int]
    components: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "span": list(self.span),
            "value": self.value,
        }
        if self.components:
            payload["components"] = dict(self.components)
        return payload

    def __hash__(self) -> int:
        """Every fact the candidate carries, hashed; nothing omitted.

        The dataclass is frozen, so Python generated a ``__hash__`` over the
        fields — and ``components`` is a mapping, so that generated hash
        raised ``TypeError`` for every candidate that carried one. Candidates
        with no components hashed fine, which is why nothing noticed until
        ``set(detect_identifier_shapes(text))``.

        Hashing the mapping's sorted pairs is the one restatement that keeps
        hash and equality answering the same question: the generated
        ``__eq__`` compares components as mappings, and two equal mappings
        have equal sorted pairs however they were built. Deduplication in
        :func:`detect_identifier_shapes` reads this same identity rather than
        a second copy of it — two spellings of "the same claim" drifting
        apart is this module's recurring defect.

        A caller who mutates a mapping after handing it to a frozen candidate
        moves the hash and the equality together, which is the ordinary
        consequence of putting a mutable value in a frozen dataclass, not a
        divergence between the two.
        """

        return hash((self.kind, self.value, self.span, tuple(sorted(self.components.items()))))


# RIN: four digits, dash, two letters, two alphanumerics.
#
# This is a chosen lexical space, not the publisher's specification, and the
# distinction is load-bearing. No universal RIN grammar is published: the RISC
# Preamble on reginfo.gov defines the RIN only by who assigns it and under
# what authority (E.O. 12866 §4(b)), and the most concrete format statement
# found anywhere is agency-specific -- the Fish and Wildlife Service's own
# handbook says "All FWS RINs begin with 1018-; the rest of the RIN consists
# of two letters followed by two numbers" (web-verified 2026-08-22), which is
# FWS describing FWS.
#
# The shape is exactly right for the roster it fences: all 46,547 Unified
# Agenda RINs conform, none excepted. It is NOT right as a description of
# every string a publisher has put in a RIN field. Five real RINs in the
# Federal Register's own ``regulation_id_numbers`` fall outside it, each
# confirmed against that API on 2026-08-22: 0648-XD990 and 0648-XC705 carry
# NOAA's five-character inseason-action suffix, and 3090-00XX, 1115-09AE and
# 2070-78AB run digit-digit-letter-letter, the reverse of the shape. None is
# in the Unified Agenda roster. They are refused here deliberately, as
# outside the mintable space rather than as malformed, and widening the shape
# to admit them would cost the fence that refuses an OMB control number.
_RIN = re.compile(rf"{_LEFT}(?P<value>\d{{4}}-[A-Za-z]{{2}}[A-Za-z0-9]{{2}}){_RIGHT}")

#: The RIN a table may PUBLISH as a key: four digits, two capitals, two
#: digits. Deliberately narrower than :data:`_RIN`, which also admits a
#: letter or a lower-case one in the last two places so the prose reader can
#: find a damaged RIN (``1625-AAOO``) or a placeholder (``2060-XXXX``) and
#: say what it found: the wider shape admits only damage or placeholders
#: (99 such values in this module's pinned columns, measured by the parsing
#: survey, spicy-docs ``docs/research/parsing-survey-2026-09-23.md`` section
#: 5), so it detects and never keys. One home for the key shape across the
#: stack; a consumer publishing a RIN calls :func:`published_rin`.
PUBLISHED_RIN = r"\d{4}-[A-Z]{2}\d{2}"
_PUBLISHED_RIN = re.compile(PUBLISHED_RIN)

#: The modern Federal Register document number, and the one lexical space the
#: downstream identifier mint admits. Four digits then three to five — a
#: shape, not a year, which is why the same expression serves detection and
#: validation and the two can never drift apart.
#: The sequence is NOT normalized: the Office of the Federal Register pads
#: some years and not others, and the padding is part of the identifier it
#: issues. Verified against the publisher's own API on 2026-08-22 --
#: 2010-5997 (2010-03-19), 2011-237 (2011-01-11), and 2012-00019 (2012-01-04)
#: are all real, and across the 480,566 modern-form values in the pinned
#: corpus not one padded number has an unpadded twin, so the literal string is
#: a safe join key and stripping zeros would only invent a spelling no
#: publisher issued. The old five-digit-only shape refused 28,862 of them.
FEDERAL_REGISTER_DOCUMENT_NUMBER = r"\d{4}-\d{3,5}"
_FR_MODERN = re.compile(FEDERAL_REGISTER_DOCUMENT_NUMBER)

#: Every form of Federal Register document number the prose reader
#: recognises, most constrained first. Only the modern form is mintable;
#: the other three are official identifiers that sit outside the mintable
#: lexical space, not outside reality, and
#: :func:`is_federal_register_document_number` refuses them deliberately.
#:
#: Order is load-bearing, because Python's alternation takes the first branch
#: that matches rather than the longest: "C1-2026-13078" must be offered to
#: the correction form before the legacy form, which would otherwise claim
#: "C1-2026" and then fail the right-hand guard. The legacy form is last for
#: the same reason -- it is the widest of the three letter-opening shapes.
#:
#: What the letters mean, web-verified 2026-08-22:
#: "C" marks a correction the Office of the Federal Register prepared itself
#: -- govinfo.gov/help/fr describes the Corrections section as holding
#: editorial corrections "prepared by the Office of the Federal Register",
#: while agency-prepared corrections "are issued as signed documents" with
#: ordinary numbers, which the Document Drafting Handbook (§5.5) repeats from
#: the agency side. The digit after it is a per-original counter, not a year:
#: C1-2012-9978 (published 2012-07-02) and C2-2012-9978 (2012-07-25) both
#: carry ``correction_of`` pointing at the same document, 2012-9978.
#: "R" marks a republication, which the publisher names in the documents
#: themselves: R1-2010-13257 is "Federal Property Suitable as Facilities To
#: Assist the Homeless; Republication", published 2010-06-04. "R1-10679"
#: satisfies the legacy form too; one alternation means one claim rather than
#: two identical ones.
#:
#: These three forms are subsets, chosen, and each refuses real numbers. The
#: Federal Register API answered 200 for every one of these on 2026-08-22:
#: Z9-802 and E9-654 (three-digit tail), E9-23 (two), Z9-9 (one), X10-11220
#: and X09-101207 (a two-digit prefix, and a six-digit tail) all fall outside
#: the legacy form; C1-2012-19, whose ``correction_of`` is 2012-00019, falls
#: outside the correction form, along with 98 other real corrections whose
#: tails run two to four digits. E3-2013-2261 -- a HUD notice, not a
#: correction -- carries a legacy prefix over a modern body and matches
#: nothing here at all. 10,340 letter-opening document numbers go unread for
#: these reasons. Widening is a recall decision with its own false-positive
#: budget in running text, not a defect to be quietly patched; the numbers
#: are here so that decision can be made with them.
_FR_DOCUMENT_FORMS: tuple[tuple[str, str], ...] = (
    ("modern", FEDERAL_REGISTER_DOCUMENT_NUMBER),
    ("correction", r"[Cc]\d-\d{4}-\d{5}"),
    ("republication", r"[Rr]\d-(?:\d{4}-)?\d{3,5}"),
    ("legacy", r"[A-Za-z]\d-\d{4,5}"),
)
_FR_DOCUMENT = re.compile(rf"{_LEFT}(?P<value>{'|'.join(form for _, form in _FR_DOCUMENT_FORMS)}){_RIGHT}")

# --------------------------------------------------------------------------- #
# The column-licensed Federal Register forms: REF-052/REF-054.
#
# Everything above this line is the PROSE reader's grammar and REF-052 leaves
# it untouched -- not one character wider than it was. What follows is what
# only a ``document_number`` field may license: the bare-legacy shape and the
# four letter-opening families the module docstring's exclusion accounting
# named above but refused to read. The prose reader still returns ``[]`` for
# every specimen below; only :func:`is_federal_register_document_number`'s
# ``column_licensed`` flag reaches them.
#
# The 10,340 letter-opening values named above split three ways, measured
# 2026-08-31 against the same pinned ``document_number`` column
# (1,004,233 distinct) this module's docstring reads: 10,231 take one of the
# four families below, each with a verified live example; 109 do not and stay
# refused, deferred rather than fixed, because REF-054 already named their
# disposition and none of it changes here:
#
# - 99 are short-tail corrections -- ``[Cc]\d-\d{4}-\d{2,4}`` -- one short of
#   the correction form's fixed five-digit tail; C1-2012-19 is the specimen
#   :data:`_FR_DOCUMENT_FORMS` already carries. Of the 99, 96 name an
#   original document the rc16 widening just made first-class (REF-054's own
#   count), 2 name one still below the widened floor, and 1 names no document
#   in the pinned column at all -- measured 2026-08-31 by resolving each
#   ``correction_of`` target against the same column. REF-054 keeps these
#   refused explicitly: widening the correction form's tail is a decision
#   about the correction form, not about the four families below, and this
#   ruling does not make it.
# - 9 are colophon-fused values carrying a trailing letter after the digits
#   ("E5-2394Filed"-shaped, with a letter-opening prefix) -- the same
#   printed-page composition defect the module's research notes attest for
#   the bare-legacy family, not a shape decision.
# - 1 is not an identifier at all: it is ``granule293`` itself, the
#   body-text extraction artifact this module's research notes attest -- it
#   opens with a letter, so the letter-opening census is where it lands.
#
# Four families, each verified against the publisher's own pages on
# 2026-08-31 (PDFs read end to end, not just the ``document_number`` cell) --
# not four guesses at what "letter-opening" might mean:
#
# **Three-digit-and-shorter tails.** The legacy form's own shape
# (``[A-Za-z]\d-\d{4,5}``) with the tail widened down to one to three digits
# -- exactly the axis rc16 widened the modern form along, and REF-054 names
# the 5,829 result as "the letter-opening family['s]... identical short-tail
# hole." E9-654 (three digits), E9-23 (two) and Z9-9 (one) are real: read
# against Federal Register Vol. 74 No. 21 (2009-02-03), E9-654's own printed
# colophon is "[FR Doc. E9-654 Filed 2-2-09; 8:45 am]" on the same page (5921)
# as "[FR Doc. E9-2239 Filed 2-2-09; 8:45 am]" and "[FR Doc. E9-2266 Filed
# 2-2-09; 8:45 am]" -- ordinary four-digit siblings in the identical numbering
# series, published the same day. The short tail is the low end of an
# ordinary sequence, not a different kind of document. 5,829 values in the
# pinned column take this shape.
_FR_LETTER_SHORT_TAIL = re.compile(r"[A-Za-z]\d-\d{1,3}")

#: **Two-digit prefixes.** A letter, TWO digits rather than the legacy form's
#: one, then its own five-digit tail -- and, measured, always exactly five:
#: no two-digit-prefix value in the pinned column carries a three- or
#: four-digit tail. X10-11220 is real (Vol. 75 No. 243, p.79449, 2010-12-20).
#: Read end to end against the publisher's PDF, it is not an ordinary
#: per-document filing: it is "Introduction to The Regulatory Plan and the
#: Unified Agenda of Federal Regulatory and Deregulatory Actions," the
#: composite front-matter section opening that fall's whole special
#: supplement, six pages long, and no "[FR Doc. ...]" colophon appears
#: anywhere in it -- unlike E9-654 above. The "X" prefix is still the
#: publisher's own ``document_number`` for the section: navigable at exactly
#: that id on both federalregister.gov and govinfo.gov. Read against the
#: whole family (4,195 values), roughly 43% (1,811 of 4,195, doc_type
#: "Uncategorized Document") are this kind of front-matter placeholder --
#: CONTENTS, Reader Aids, Subscriptions boilerplate, Regulatory Plan
#: introductions, "[No title available]" -- rather than a substantive rule or
#: notice; the remaining 57% (2,384 of 4,195: 1,570 Corrections, 566 Notices,
#: 164 Rules, 49 Proposed Rules, 17 Presidential Documents, 15 Sunshine Act
#: Documents) are ordinary filings that do carry their own colophon. Both
#: populations are real values the publisher's own API puts in
#: ``document_number``, and the column doctrine reads shape, not editorial
#: content -- the same posture this module's research notes already take for
#: ``granule293``, the Reader Aids placeholder that "even it is the
#: publisher's."
_FR_TWO_DIGIT_PREFIX = re.compile(r"[A-Za-z]\d{2}-\d{5}")

#: **Six-digit tails.** A letter, exactly two digits, then a SIX-digit tail --
#: measured exactly, because zero one-digit-prefix, six-digit-tail values
#: exist in the pinned column; that unobserved shape stays refused rather
#: than admitted on the strength of the family's name alone. X09-101207 is
#: real (Vol. 74 No. 233, p.64213, 2009-12-07) and reads the same way as its
#: two-digit-prefix sibling above: the Fall 2009 Regulatory Plan itself, 33
#: pages closing with FEMA's "Special Community Disaster Loans Program" entry
#: at p.64245, no colophon on either bounding page, still the publisher's own
#: id. 206 values in the pinned column take this shape.
_FR_SIX_DIGIT_TAIL = re.compile(r"[A-Za-z]\d{2}-\d{6}")

#: **Legacy-prefix-over-modern-body hybrids.** A letter and one digit, then
#: the modern form's own body whole: a second dash, a four-digit year, a
#: three-to-five-digit tail. Exactly one value in the pinned column takes
#: this shape: E3-2013-2261, read against Vol. 78 No. 22 p.7443 (2013-02-01,
#: "Request for Comment on the Redesign of the American Housing Survey"),
#: whose own printed colophon -- "[FR Doc. E3-2013-2261 Filed 1-31-13; 8:45
#: am]" -- sits in the same place and style as every ordinary document's on
#: the same page. C and R are excluded by construction, not by absence in the
#: data alone: a C-prefixed value in this exact shape is one of the 99
#: short-tail corrections named above and stays in that deferred population,
#: and an R-prefixed value in this shape is already read by the
#: republication form, whose own year segment is optional
#: (``r"[Rr]\d-(?:\d{4}-)?\d{3,5}"``). Neither is this family.
_FR_LEGACY_OVER_MODERN_BODY = re.compile(r"(?![CcRr])[A-Za-z]\d-\d{4}-\d{3,5}")

#: The four families above, tried in no particular order -- safe because
#: they are disjoint BY CONSTRUCTION, not by census: under ``fullmatch`` the
#: legacy-over-modern form is the only one with two dashes; among the
#: one-dash forms the short tail requires exactly one digit before the dash
#: where the other two require exactly two; and those two demand five-
#: versus six-digit tails. No string can satisfy two of them at once, so
#: order cannot matter.
_FR_COLUMN_LETTER_FORMS: tuple[re.Pattern[str], ...] = (
    _FR_LETTER_SHORT_TAIL,
    _FR_TWO_DIGIT_PREFIX,
    _FR_SIX_DIGIT_TAIL,
    _FR_LEGACY_OVER_MODERN_BODY,
)

#: The pre-modern Federal Register document number: a two-digit year, a
#: hyphen, and the sequence. "09-19806" is one; so is every document the
#: Register published from 1994-01-03 through 2009-08-19 that did not carry a
#: letter prefix.
#:
#: **394,128 of the 1,004,233** distinct values in the pinned
#: ``document_number`` column take this shape -- 39.2%, measured 2026-08-31 --
#: and it is now a licensed column family rather than the class appearing
#: nowhere in this module's accounting: ``detect_identifier_shapes("09-19806")``
#: still returns ``[]`` (the prose reader is unchanged), but
#: ``is_federal_register_document_number("09-19806", column_licensed=True)``
#: is ``True``. Read against Vol. 74 No. 159 p.41908 (2009-08-19), its own
#: printed colophon is "[FR Doc. 09-19806 Filed 8-18-09; 1:15 pm]" -- the
#: Federal Trade Commission's "CSE, Inc., et al." consent-order notice.
#:
#: **The column is the license.** This shape is unusable in running text --
#: unlabeled, "94-12345" is indistinguishable from "MM Docket No. 98-213" and
#: from a release number, which is why the prose reader refuses it and stays
#: refusing it. A value arriving from a ``document_number`` field needs no
#: such inference: the field already said what it holds.
#:
#: The tail runs three to SIX digits. Three to five is the modern shape's own
#: floor and ceiling (``FEDERAL_REGISTER_DOCUMENT_NUMBER``) and covers 394,121
#: of the values; the six-digit tail adds exactly 7, and all 7 are real
#: published documents rather than damage -- 94-120124, 94-126624, 95-170007,
#: 95-229994, 95-295759, 96-244797 and 97-339151, each carrying its own
#: ``federalregister.gov/documents/...`` URL, volume and page in the pinned
#: corpus. A six-digit tail is a form the publisher really issued, which the
#: letter-opening family already witnesses (X09-101207, above).
#:
#: NOT THIS CONSTANT'S, AND NO LONGER REFUSED: 1,370 further values are
#: ``\d{2}-\d{1,2}`` -- "00-10" and "00-11" are real airworthiness directives
#: of 2000-01-04, printed two pages apart in the same issue (65 FR 209 and
#: 65 FR 207). REF-052 named them a refusal and deferred them; REF-056
#: licensed them through the SIBLING production
#: :data:`_FR_BARE_LEGACY_SHORT_TAIL` below rather than by widening this
#: constant, so this shape's own tail still starts at three digits and its
#: 394,128 count -- quoted outside this module, in ``iri_minting.py`` -- is
#: unmoved by that ruling. The 109 letter-opening values above do stay
#: refused, and that posture is unchanged.
#:
#: Moved home 2026-08-31 (REF-052): this constant lived in ``iri_minting.py``
#: behind a "long-term home" note because this module is content-hashed into
#: a build receipt and editing it forces an artifact rebuild. The bare-legacy
#: mint itself does not change -- ``mint_federal_register_document_iri``'s
#: ``column_licensed`` flag reads exactly the shape it read before, now from
#: here.
BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER = r"\d{2}-\d{3,6}"
_FR_BARE_LEGACY = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)

# --------------------------------------------------------------------------- #
# REF-056: the widening cycle after REF-052/REF-054, over the same pinned
# ``document_number`` column re-measured 2026-08-31. Two more productions,
# each a NEW named constant rather than a rewrite of one above -- widening
# :data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER` itself would move its
# own documented count (394,128) and this module is not the only reader of
# that number. Both stay disjoint from every existing family BY
# CONSTRUCTION: a fullmatch fixes the digit count on both sides of the dash,
# so a value with a two-digit year can never also have a four-digit one, and
# neither shape opens on a letter, so neither can collide with
# :data:`_FR_COLUMN_LETTER_FORMS`.
#
# **Bare-legacy short tails.** The bare-legacy shape's own floor, widened
# down the identical axis rc16 widened the modern form along and REF-052
# widened the letter-opening family along: one or two digits rather than
# three to six. "00-1" (EPA's Amino/Phenolic Resins NESHAP, 65 FR 3276,
# 2000-01-20) and "00-10" (an FAA airworthiness directive, 65 FR 207,
# 2000-01-04) are real, each read end to end against the publisher's own PDF
# with its own printed colophon -- "[FR Doc. 00-1 Filed 1-19-00; 8:45 am]"
# and "[FR Doc. 00-10 Filed 1-3-00; 8:45 am]" -- in the identical place and
# style as every ordinary document's. "93-54" witnesses a sub-cluster worth
# naming: filed 1994-01-03 for the 1994-01-04 issue, it still carries the
# outgoing year's two-digit token, which is why "93-"-prefixed values exist
# at all inside a corpus whose bare-legacy era is documented as opening
# 1994-01-03 -- a document FILED before the era's first PUBLISHED document
# can still carry the year it was filed under. 1,370 values in the pinned
# column take this shape: 112 with a one-digit tail, 1,258 with two. Twenty
# four specimens (this family and the next), stratified by tail length and
# by year, are read in research/evidence/fr-short-tails-2026-08-31/.
_FR_BARE_LEGACY_SHORT_TAIL = re.compile(r"\d{2}-\d{1,2}")

#: **Modern short tails.** The modern form's own shape with a one- or
#: two-digit tail rather than three to five -- admitted to the partner hatch
#: ONLY, not to rulespec's own mintable space. This is not the same event as
#: rc16's widening: :data:`FEDERAL_REGISTER_DOCUMENT_NUMBER` and ``_FR_MODERN``
#: are untouched by this constant, and the prose reader still refuses every
#: value here exactly as it did before -- REF-056 widens what the COLUMN
#: licenses, the way REF-052 did for the letter-opening family and bare-legacy
#: itself, and leaves the mintable lexical space for a separate ruling with
#: its own budget. "2010-1" (an SEC notice of application, 75 FR 1007,
#: 2010-01-07) and "2010-10" (a DOE notice, 75 FR 983, 2010-01-07) are real,
#: each with its own printed colophon in the ordinary place. 286 values in the
#: pinned column take this shape: 27 with a one-digit tail, 259 with two --
#: clustered in 2010-2012 with one outlier, "2013-58" -- colophoned "[FR Doc.
#: 2013-58 Filed 1-2-13; 4:15 pm]" on 78 FR 908, one page after "[FR Doc.
#: 2012-31431 Filed 1-4-13; 8:45 am]" on 78 FR 907, both in the issue of
#: 2013-01-07. What those two witnesses establish is narrow, and it is
#: stated narrowly: the year token is determined by NEITHER date printed on
#: the page. Not by publication -- one issue carries both tokens. Not by
#: filing either -- the 2012-token document was filed 1-4-13, two days AFTER
#: the 2013-token one. "93-54" above is the same fact from the other side of
#: a year boundary. What DOES decide the token is not established here: no
#: source this lane retained records a submission timestamp, so reading a
#: per-submission rollover off these pages would be an inference rather than
#: a reading, and the column doctrine needs only the shape.
_FR_MODERN_SHORT_TAIL = re.compile(r"\d{4}-\d{1,2}")

#: The leading token of a docket is an agency code, capped at two to six
#: letters ("EPA", "FSIS", "USCIS"). Without the cap, "letter then anything"
#: reads a hyphenated English word as an agency and
#: "documentation-2021-0317" mints docket DOCUMENTATION-2021-0317. Later path
#: segments keep the looser shape, because real dockets write office and
#: program codes there ("EPA-HQ-OAR", "AMS-SC").
_DOCKET_ORGANIZATION = r"[A-Za-z]{2,6}(?:[-_][A-Za-z0-9]+)*"

#: A four-digit year for the prose reader; a label licenses the two-digit
#: form as well. This parameter is the whole of that rule, so the rule is
#: visible rather than distributed across two hand-copied patterns. Each is a
#: self-contained group, so a caller can quantify or anchor it without the
#: alternation leaking into what surrounds it.
_DOCKET_YEAR = r"(?:\d{4})"
_DOCKET_YEAR_LICENSED = r"(?:\d{4}|\d{2})"

#: The office or program code an agency writes between the year and the
#: sequence, and the run of them when it writes more than one:
#: "FDA-2026-N-0008", "EERE-2022-BT-OT-0004". Both are real Regulations.gov
#: dockets — that API answered 200 for each on 2026-08-22, and the Federal
#: Register API calls each an "agency docket" — so the repeat is the
#: publisher's, not a tolerance.
#:
#: LETTERS ONLY, and that is the whole of the fence. A segment that could
#: carry digits reads "EPA-HQ-OAR-2021-0317-0001" as
#: organization-year-office-sequence, which turns every Regulations.gov
#: document id into a docket claim; letters cannot spell 0317. The run is one
#: group, so the components still reconstruct the value, and the group is
#: optional, so a docket that states no office reports none.
_DOCKET_OFFICE = r"(?:(?P<office>[A-Za-z]+(?:[-_][A-Za-z]+)*)[-_])?"

#: The trailing token a Regulations.gov docket id may END on, and the whole
#: of it — a CLOSED vocabulary of five, not an "ends on letters" licence.
#:
#: The fence above refuses a docket that ends on letters, and it is right to:
#: that fence is what keeps "Internal Agency Docket No. FEMA-1971-DR" and the
#: disaster numbers out. But it also refused a real docket. The pinned
#: docket column states one in the publisher's own words — "Docket
#: #GIPSA-2010-FGIS-0014-NONRULEMAKING", labelled a docket and ending on the
#: token — and the module's own comment named
#: "GIPSA-2008-FGIS-0002-NONRULEMAKING" as something the fence refuses,
#: without noticing it was refusing a docket rather than a malformation.
#:
#: Measured over the 1,943,108 Regulations.gov document ids in spicy-docs'
#: sealed corpus (receipt: ``supply-2026-09-02/receipts/
#: document-id-segment-census.json``), exactly five distinct tokens ever
#: appear here, across 134 ids: NONRULEMAKING 98, RULEMAKING 28, NONRULE 4,
#: DRAFT 2, RULE 2. The vocabulary is spelled out rather than generalized to
#: ``[A-Za-z]+`` because generalizing reopens the fence this closes.
#:
#: TWO no-regression measurements, because one is scoped narrowly and saying
#: so is the point. Over this repository's four pinned columns (1,665,260
#: distinct values) exactly ONE answer changes and it gains a claim -- but
#: those columns hold only 179 document-kind values in total, so that result
#: shows no regression IN THIS CORPUS and is not evidence about the population
#: at risk. Over the population that actually carries these ids -- 371 GIPSA
#: document ids and 105 publisher-stated docket ids -- 199 answers change and
#: ZERO lose a claim. The corrections are the point:
#: GIPSA-2008-FGIS-0002-NONRULEMAKING-0003 read as a DOCKET with year "0002"
#: and organization "GIPSA-2008-FGIS"; it now reads as a document, year 2008.
#:
#: The token is POSITIONAL here, not semantic, and the group's name says so.
#: Four of the five classify the proceeding; DRAFT classifies the document's
#: state. A component named for either meaning would be wrong for the other,
#: so the grammar reports WHERE the token sat and declines to say what it
#: means. The vocabulary is deliberately HETEROGENEOUS -- four of the five
#: name a proceeding kind, DRAFT names a document state -- so membership here
#: says nothing about meaning, and nobody should later infer that DRAFT is a
#: proceeding because it shares this group with RULEMAKING.
#:
#: The token belongs to the DOCKET, and that is measured rather than assumed.
#: Regulations.gov's own ``docketId`` attribute states it: across the 371
#: GIPSA document records in spicy-docs' sealed corpus, 132 carry the token
#: and every one satisfies ``documentId startswith docketId + "-"`` with ZERO
#: violations, over 67 distinct docket ids that themselves end on a token.
#: The rule is PREFIX CONTAINMENT and not "docket plus one numeric segment":
#: stated the narrow way it survives this 917-record sample and fails at
#: scale, where spicy-regs measured 40,485 documents of 1,797,201 whose tail
#: is TWO segments ("DOT-OST-1995-125-0050-0001" in docket
#: "DOT-OST-1995-125"). The narrow phrasing is what this sample happened to
#: license, which is why it is corrected here rather than left to be
#: rediscovered. That is why the group lives in ``_docket_body`` -- shared by the
#: docket grammars AND inherited by the document grammar -- rather than being
#: wedged into the document grammar alone. An earlier reading rested on a
#: single free-text reference in the pinned column and would have been
#: generalizing from one filled-in form field; the publisher's own attribute
#: replaced it.
#:
#: Two cautions the evidence forces. The docket RELEASE for this agency holds
#: 38 dockets, NONE with an office segment or a token, carrying the type in a
#: ``docketType`` ATTRIBUTE instead. The obvious explanation -- that the
#: release predates the token-bearing form -- was checked and does NOT hold:
#: its records carry modifyDates in 2006, 2008, 2011 and 2021, so it is not
#: era-bound, and ``GIPSA-2006-FGIS-0030-RULE`` is absent from it even though
#: 2006 is squarely inside its span. Its ``GIPSA-2006-NNNN`` run is 1..27 with
#: no gaps, so it is complete for the family it does carry. Two docket-id
#: FAMILIES therefore coexist, and this release mirrors only the one without a
#: token; the token-bearing form is evidenced by the documents' ``docketId``
#: field instead. A consumer joining on docket id across both sees two shapes
#: for one concept and only one of them is visible to this grammar, so a
#: token-aware reader will look more complete than the data is.
#:
#: And DRAFT is evidenced differently from the other four: two instances, two
#: agencies, with no docket record in hand for either.
#:
#: The alternation is written longest-first for reading, and that ordering is
#: NOT load-bearing -- stated because the opposite is the natural assumption
#: and a future reader may otherwise "fix" an order that never mattered.
#: Every one of the six orderings returns the identical segment for all five
#: tokens, because the group is followed by an anchor (a document sequence,
#: or end-of-value) that no short branch can satisfy: matching RULE out of
#: NONRULEMAKING strands MAKING in front of the anchor, the match fails, and
#: the engine backtracks to the only branch that completes. A mutation
#: reversing the order leaves the suite green, which is the measurement
#: behind this comment rather than a reassurance about it.
_DOCKET_SEGMENT_TOKENS = "NONRULEMAKING|RULEMAKING|NONRULE|RULE|DRAFT"
_DOCKET_SEGMENT = rf"(?:[-_](?P<segment>{_DOCKET_SEGMENT_TOKENS}))?"


def _docket_body(year: str, sequence_group: str = "sequence", office: str = "") -> str:
    """Organization, year, sequence — the shape all three docket grammars share.

    The office segment is a parameter for the same reason the year is: all
    three grammars read it, mirrored onto the Regulations.gov document
    grammar rather than restated for it. Before this rule, that grammar had
    nowhere for "BT-PET" to go, so the docket grammar's own organization
    group — which absorbs any alnum continuation segment, not only letters —
    swallowed it instead: "EERE-2019-BT-PET-0019-0008" read as docket
    organization EERE-2019-BT-PET, "year" 0019, "sequence" 0008. It was
    already a right answer, docket EERE-2019-BT-PET-0019 and document 0008,
    so mirroring the segment here corrects a decomposition rather than
    admitting anything new: 11 references in the pinned docket column (13
    occurrences) move this way, named in
    ``test_the_office_segment_is_measured_over_the_real_docket_column``.

    A second, larger effect rides along, and it is not a rewrite of anything:
    the document grammar's own sequence has always run three to six digits,
    wider than a docket's three to five, and a six-digit tail like
    "...-200539" could not be read AT ALL before — not even as a wrong
    docket — because neither grammar had anywhere for the office letters in
    front of it to go. 36 further references (36 occurrences) gain a prose
    answer they never had. Both counts are measured in the same test.
    """

    return (
        rf"(?P<organization>{_DOCKET_ORGANIZATION})"
        rf"[-_](?P<year>{year})[-_]{office}(?P<{sequence_group}>\d{{3,5}})"
        rf"{_DOCKET_SEGMENT}"
    )


#: "Docket No. FSIS-2025-0012", "DHS Docket No. USCIS-2025-0004",
#: "Docket #: EPA-R10-OAR-2014-0808", "Docket Nos. FDA-2025-E-0162". One
#: vocabulary, read below both inline (by the prose reader) and anchored (by
#: the column reader), because the two spellings drifting apart is this
#: module's recurring defect: the inline one admitted a single ``[:#]`` while
#: the anchored one had learned the hyphen and the doubled punctuation, and
#: the anchored one spelled the counter word as an alternation whose first
#: branch swallowed the singular out of "Nos.".
#:
#: The label noun is a whole word. "doc" unbounded ate the head of
#: "Document", "Doctrine" and "Documentation" and minted the remainder as an
#: agency code.
#:
#: The whitespace and punctuation runs are possessive: nothing after them can
#: begin with a space or with ``:#-``, so giving characters back never makes
#: a match, and three adjacent runs that could each take the same spaces made
#: a failed match cubic in them ("Docket" and 1,000 spaces took 1.8 s,
#: measured 2026-09-26). What the label reads is unchanged.
_DOCKET_LABEL = rf"(?:dockets?|docs?)\b\.?\s*+{_LABEL_COUNTER_WORD}?\s*+[:#\-]*+\s*+"

_DOCKET_BARE = re.compile(rf"{_LEFT}(?P<value>{_docket_body(_DOCKET_YEAR, office=_DOCKET_OFFICE)}){_RIGHT}")
#: The label is presentation, never part of the identifier: it sits outside
#: the ``value`` group, so the span and the value exclude it by construction
#: rather than by index arithmetic downstream.
_DOCKET_LABELED = re.compile(
    rf"\b{_DOCKET_LABEL}(?P<value>{_docket_body(_DOCKET_YEAR_LICENSED, office=_DOCKET_OFFICE)}){_RIGHT}",
    re.IGNORECASE,
)
_REGULATIONS_GOV_DOCUMENT = re.compile(
    rf"{_LEFT}(?P<value>{_docket_body(_DOCKET_YEAR, 'docket_sequence', office=_DOCKET_OFFICE)}"
    rf"[-_](?P<document_sequence>\d{{3,6}})){_RIGHT}"
)
#: The same vocabulary, anchored at the start of a value. A department may
#: name itself in front of the label ("DHS Docket No.", "STB Docket No."),
#: capped at one word of two to six letters. Widening that cap gains nothing
#: measured: "Internal Agency Docket No. FEMA-1971-DR" (2,918 distinct
#: references) is refused by the shape below for ending on letters, not for
#: the two words in front of its label.
_DOCKET_LABEL_PREFIX = re.compile(rf"^\s*(?:[A-Za-z]{{2,6}}\s+)?{_DOCKET_LABEL}", re.IGNORECASE)

#: The uppercase lexical space a Regulations.gov identifier must live in
#: before it is one at all.
_REGSGOV_VALID = re.compile(r"[A-Z0-9]+(?:[-_][A-Z0-9]+)*")

#: What the column reader requires of a value, or of what a stripped label
#: uncovered, for it to be an identity: organization, then year, then
#: sequence — and the organization opens on a LETTER. See the module
#: docstring for the 5,214/5,506 measurement.
#: The second alternative is the year-less FRDOC family: every agency holds
#: exactly one "AGENCY_FRDOC_0001" docket on Regulations.gov for its
#: Federal Register documents (web-verified 2026-08-22: ACF_FRDOC_0001 is
#: real and navigable; 72,404 catalog document rows and 177 docket rows
#: carry the family, measured on the pinned regulatory-native columns).
#: The literal FRDOC token is the anchor the missing year would otherwise
#: provide.
#:
#: This is looser than the prose reader's grammar in three ways, each of
#: which the column licenses and running text would not: the organization is
#: uncapped, the year may be two digits with no label, and the sequence may
#: be any number of digits rather than three to five. The office segment
#: between year and sequence ("FDA-2026-N-0008") is NOT one of them any more
#: — both readers read it, because letters cannot be mistaken for the
#: sequence of a Regulations.gov document id. It ends on digits, which is
#: the fence that refuses the FEMA disaster numbers -- or on one of the
#: prose reader's closed five trailing tokens (:data:`_DOCKET_SEGMENT`),
#: which the column reader refused until 2026-09-23 although the prose
#: reader already read them: 67 of the retained Regulations.gov documents
#: table's 278,370 distinct ``docket_id`` values end on one
#: ("GIPSA-2006-FGIS-0029-NONRULE"; NONRULEMAKING 47, RULEMAKING 14, NONRULE
#: 4, RULE 2), each the publisher's own statement of a document's docket,
#: and no other value in that column or in the dockets table's 279,124 was
#: refused but one. That one, GSA-NA-2005, states no sequence at all, and
#: stays refused: admitting organization-office-year would admit every
#: number with that silhouette.
#: The two-digit year is real rather than tolerated: AMS-SC-25-0848 is cited
#: by Federal Register document 2026-14918, and regulations.gov's own API
#: answers 404 for it rather than the 400 it returns for a malformed id
#: (web-verified 2026-08-22), so the shape is one that service recognises.
#:
#: FERC eLibrary dockets fit this shape and are NOT Regulations.gov dockets;
#: `_FERC_DOCKET` below excludes them, and `numbering_system` names them.
#: The shape still admits any other agency's own numbering that happens to
#: read as organization-year-sequence, which is why a docket answer is a
#: statement about shape and the numbering system is a separate question.

_FERC_DOCKET_PREFIXES = (  # noqa: SIM905 -- a list literal would flatten this into one ~800-char line; the wrapped string stays readable
    "AC AD AI CD CE CP CX DI DO DR DV EC EF EG EL EM EP ER ES ET EX EY FA FC GP GT GX HC IN IS "
    "JR LA LP MC MD MG ML MO MT NJ NL NP NR OA OR OT PA PF PH PL PR QF QM RA RC RD RM RO RP RR "
    "RS RT SA SC TC TF TM TQ TS TX UL ZZ"
).split()
#: prefix, two-digit year, sequence, and the optional three-digit sub-docket
#: FERC appends to every filing in a proceeding.
_FERC_DOCKET = re.compile(rf"(?:{'|'.join(_FERC_DOCKET_PREFIXES)})\d{{2}}-\d+(?:-\d{{3}})?")

_REGSGOV_FRDOC_DOCKET = re.compile(r"[A-Z][A-Z0-9]{1,9}_FRDOC_\d{4}")
_DOCKET_SEGMENT_TOKEN_SET = frozenset(_DOCKET_SEGMENT_TOKENS.split("|"))


def _has_regsgov_docket_shape(identifier: str) -> bool:
    """Whether a :data:`_REGSGOV_VALID` identifier has the column reader's docket shape, described above.

    The organization's first segment opens on a letter; the last segment is
    the sequence, all digits, unless one of the closed trailing tokens follows
    it; and some segment between the two is a two- or four-digit year. Read
    segment by segment, once. As one regular expression --
    ``[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*[-_]\\d{2}(?:\\d{2})?(?:[-_][A-Z0-9]+)*[-_]\\d+``
    and the optional token -- the two free runs of segments around the year
    were tried pair by pair, quadratic in a long hyphenated token (2.3 s for
    one of 52,000 characters, measured 2026-09-26); the test that replays it
    against this function keeps the answer the same.
    """

    if _REGSGOV_FRDOC_DOCKET.fullmatch(identifier):
        return True
    organization, *segments = re.split(r"[-_]", identifier)
    if segments and segments[-1] in _DOCKET_SEGMENT_TOKEN_SET:
        segments.pop()
    if not organization[:1].isalpha() or len(segments) < 2 or not segments[-1].isdigit():
        return False
    return any(len(segment) in (2, 4) and segment.isdigit() for segment in segments[:-1])


#: The spellings a stringified null leaves behind, shared by every reader of a
#: docket column so all of them agree on what "no reference" looks like.
#: Deliberately case-sensitive: these are what ``str(None)``,
#: ``str(float("nan"))`` and JSON's ``null`` produce, and no case-variant
#: spelling occurs in any of the four pinned columns, so widening the set
#: could only start swallowing real references.
_UNSTATED_SENTINELS = frozenset({"", "None", "nan", "null"})


# --------------------------------------------------------------------------- #
# Validators and normalizers — whole-string answers only.


def is_regulation_identifier_number(value: object) -> bool:
    """Whether a value is, in whole, a Regulation Identifier Number."""

    return normalize_rin(value) is not None


def published_rin(value: object) -> str | None:
    """The RIN a value states, in the one shape a published key may take, or ``None``.

    Dashes and letter case fold first, as every reader here folds them
    (``3133–af97`` is ``3133-AF97``); then the whole value must be
    :data:`PUBLISHED_RIN`. :func:`normalize_rin` is the wider, detection-side
    answer and is never a key.
    """

    text = _folded_text(value)
    return text if _PUBLISHED_RIN.fullmatch(text) else None


def normalize_rin(value: object) -> str | None:
    """The canonical RIN a value states, or ``None`` when it states none."""

    text = _folded_text(value)
    return text if _RIN.fullmatch(text) else None


def is_federal_register_document_number(value: object, *, column_licensed: bool = False) -> bool:
    """Whether a value is a Federal Register document number.

    Prose-narrow by default (``column_licensed=False``, unchanged): only the
    modern form is ``True``. Legacy, correction and republication numbers are
    official and deliberately ``False`` here — they are outside the mintable
    lexical space, not outside the corpus, and :func:`detect_identifier_shapes`
    reads all four regardless of this flag, because prose detection is not
    conditioned on the column license at all.

    ``column_licensed=True`` is REF-052/REF-054's ruling in one parameter: a
    value arriving from a trusted ``document_number`` field is additionally
    recognised as the bare-legacy shape
    (:data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`) or one of the four
    letter-opening families named at :data:`_FR_COLUMN_LETTER_FORMS`, each
    verified against the publisher's own pages. REF-056 widens the same
    license two further steps: the bare-legacy shape's own one- and
    two-digit tail (:data:`_FR_BARE_LEGACY_SHORT_TAIL`) and the modern
    shape's own one- and two-digit tail (:data:`_FR_MODERN_SHORT_TAIL`),
    admitted to the partner hatch only — the latter does NOT touch rulespec's
    own mintable space, which stays exactly ``FEDERAL_REGISTER_DOCUMENT_NUMBER``
    wide. It does NOT additionally admit the correction, republication or
    legacy forms :data:`_FR_DOCUMENT_FORMS` already carries — those are read
    by the prose grammar unconditionally, via :func:`detect_identifier_shapes`,
    so restating them here would be a second, driftable copy of the same
    rule. Nothing about prose detection changes either way: the flag only
    ever adds to what THIS function answers.
    """

    text = _folded_text(value)
    if _FR_MODERN.fullmatch(text):
        return True
    if not column_licensed:
        return False
    if _FR_BARE_LEGACY.fullmatch(text) or _FR_BARE_LEGACY_SHORT_TAIL.fullmatch(text):
        return True
    if _FR_MODERN_SHORT_TAIL.fullmatch(text):
        return True
    return any(pattern.fullmatch(text) for pattern in _FR_COLUMN_LETTER_FORMS)


#: Damage operators for a Regulation Identifier Number, each named and each
#: reversible: the homoglyph pairs a keyboard or an OCR pass confuses, and the
#: two ways a hyphen goes missing. Nothing here invents a character that was
#: not already suggested by the one it replaces.
_RIN_HOMOGLYPHS: Mapping[str, str] = {
    "O": "0",
    "0": "O",
    "I": "1",
    "1": "I",
    "S": "5",
    "5": "S",
    "B": "8",
    "8": "B",
    "Z": "2",
    "2": "Z",
}


def _rin_damage_variants(text: str) -> set[str]:
    """Every reading one named operator away from the value as written.

    The value as written is included, so the set reads as "at most one
    operator applied". Homoglyphs are tried in every position rather than
    only in the sequence: "O301-AA00" is damage in the agency prefix, and
    253 occurrences in the pinned RIN column are damage in the sequence.
    """

    variants = {
        text,
        text.replace(" ", "-", 1),  # the hyphen became a space
        text.replace(" ", "", 1),  # the hyphen vanished and a space took its place
    }
    for index, character in enumerate(text):
        replacement = _RIN_HOMOGLYPHS.get(character)
        if replacement is not None:
            variants.add(text[:index] + replacement + text[index + 1 :])
    return variants


def corrected_rin(value: object, roster: Container[str]) -> tuple[str, str] | None:
    """The RIN a damaged value states, corroborated, or ``None``.

    Fail-closed and oracle-fenced, the same contract the Public Law correction
    uses: candidates come only from named damage operators, each candidate
    must EXIST in a pinned roster of real RINs, and exactly one may survive.
    A value that is already a RIN is never "corrected", and a value whose
    repairs reach two roster entries is refused rather than chosen between.

    The roster is the fence. Measured against the Unified Agenda's own 46,547
    RINs, over every value the Federal Register's RIN column states and this
    module's shape refuses -- 390 distinct, 588 occurrences -- this resolves
    269 distinct (421 occurrences) to exactly one survivor and refuses 121
    distinct (167 occurrences). Both numbers are given in both units on
    purpose: a distinct count and an occurrence count are different
    measurements, and quoting one as the other is how a rate stops meaning
    anything.

    The refusals are three named things:

    - 56 distinct (89 occurrences) are OMB control numbers filed in a RIN
      field ("3235-0695"), which no single operator can turn into a RIN.
    - 55 distinct (67 occurrences) reach a well-formed RIN the roster does
      not hold -- "0648-X081" reaches "0648-XO81" -- which is the roster's
      limit rather than the value's defect.
    - 10 distinct (11 occurrences) reach no well-formed RIN at all.

    Not everything this function is handed is damaged. Five of those 390 are
    real RINs outside the shape ``_RIN`` fences -- 0648-XD990, 0648-XC705,
    3090-00XX, 1115-09AE, 2070-78AB, each confirmed against the Federal
    Register API on 2026-08-22 -- and refusing them is the correct answer for
    the same reason as everything else here: no roster entry is one named
    operator away, so there is nothing to corroborate.

    ``test_the_corrector_answers_the_real_damaged_population`` re-runs that
    measurement over both columns, so these counts break when they stop
    being true.
    """

    text = _folded_text(value)
    if not text or normalize_rin(text) is not None:
        return None
    survivors = {
        candidate
        for candidate in (normalize_rin(variant) for variant in _rin_damage_variants(text))
        if candidate is not None and candidate in roster
    }
    if len(survivors) != 1:
        return None
    return survivors.pop(), "unique-roster-existence"


#: The widest sequence any document-number form here carries (the six-digit
#: tails), so every zero-padded spelling of a key is within reach of it.
_WIDEST_SEQUENCE = 6

#: A run of dashes and spaces where a document number's one hyphen stands:
#: Regulations.gov's ``fr_doc_num`` types a space for it ("99 20888", "E8
#: 21218"), spaces around it ("2011 - 7212", "E7- 21472") and doubles it
#: ("2020--19543"). No form here separates a letter prefix from its digit, so
#: a separator there goes ("E-9-18682"). Only the comparison key folds these;
#: see :func:`unpadded_federal_register_document_number`. (Not named ``_FR_*``:
#: the tests' ``_FR_`` census partitions the document-number forms.)
_DOCUMENT_NUMBER_SEPARATOR = re.compile(r"[\s-]+")
_LETTER_PREFIX_SEPARATOR = re.compile(r"^([A-Z])-(?=\d)")


def _unpadded_sequence(sequence: str) -> str:
    """A document-number sequence without its zero padding: ``00239`` -> ``239``, ``00000`` -> ``0``.

    The one zero-padding rule the join-side document-number normalizers share:
    the Office of the Federal Register pads some years and not others, and
    regulations.gov pads where the Register did not.
    """

    return sequence.lstrip("0") or "0"


def unpadded_federal_register_document_number(value: object) -> str | None:
    """The key a Federal Register document number is compared on: its sequence without zero padding.

    ``2010-02394`` is ``2010-2394`` and the legacy ``E9-09366`` is ``E9-9366``;
    only the digits after the last hyphen move, so ``C1-2012-09978`` keeps its
    year. A value has a key when some zero-padded spelling of that key is a
    document number in a form this module reads -- column-licensed
    (:func:`is_federal_register_document_number`) or prose (the correction,
    republication and legacy forms) -- so a docket or a RIN never has one, and
    the key is a fixed point: ``C1-2012-9978``, which the correction form's
    fixed five-digit tail refuses as written, keys to itself because
    ``C1-2012-09978`` is read.

    **A comparison key, not an identifier.** The literal string stays the
    identifier (:data:`FEDERAL_REGISTER_DOCUMENT_NUMBER`): the Office of the
    Federal Register pads some years and not others, and its own
    ``document_number`` column holds 135,264 padded numbers -- every modern
    year from 2013 pads -- beside unpadded ones before it. Regulations.gov's
    ``fr_doc_num`` pads where the Register did not, which is why 49,403
    Federal Register references in the rulemaking build's ``rule_targets``
    were ``missing``. Two counts of what unpadding recovers, with their
    bases: 40,340 by the parsing survey's rule (spicy-docs
    ``docs/research/parsing-survey-2026-09-23.md`` section 2, item A7), which
    strips the zeros of an already-upper-case reference and looks the result
    up literally; and 41,372 by this key, measured 2026-09-23 over the same
    tables with both sides reduced, the exact string tried first and a key
    reaching two held numbers refused. The second holds all of the first; the
    1,030 more are 936 en-dash references, 79 unpadded references to padded
    numbers and 15 others. No key reached two documents.

    So a join reduces **both** sides to this key and tries the exact string
    first: unpadding only the reference would break the 2013-onward matches
    that are exact today. The key is not unique over the whole column: of
    1,008,522 distinct document numbers measured 2026-09-23, five bare-legacy
    pairs from 1994-1997 reduce to one key each (``94-0190`` and ``94-190``
    are different documents, published 1994-04-26 and 1994-01-05), so a key
    that reaches more than one held number is refused, not chosen between.

    **The separators Regulations.gov types fold too** (2026-09-26, drift
    audit defect D2): a run of spaces and dashes where the hyphen stands
    ("99 20888", "2011 - 7212", "2020--19543") is one hyphen, and a separator
    between a letter prefix and its digit goes ("E-9-18682"). No form here
    reads either spelling, so a value keyed before keys the same; the fold
    only gives a key to a value that had none. Measured over the audit's
    inputs (receipt ``fork-execution-2026-09-21/drift-qualification-2026-09-26/
    regulatory/d1d2-fix``): no key of the 1,008,830 held numbers moves, the
    same five bare-legacy pairs collide and no other; of 454,231 distinct
    ``fr_doc_num`` values 52 gain a key and 38 resolve: exactly the values
    behind the 39 references the audit found ``missing``, "99 20888" among
    them, whose resolution makes FDA-1999-F-0118 an action docket. The other
    14 are pre-1994 numbers and page ranges ("8307 - 8309") that reach no held
    number.

    The zero-padding rule itself is the shared :func:`_unpadded_sequence`;
    this function keeps its own admission forms and its wide folds -- every
    dash spelling (:func:`_folded_text`) and the typed separators above --
    where the strict join-side normalizers below fold only the measured en
    dash. Its keys are pinned for consumers such as spicy-regs'
    ``FederalRegisterIndex``: a change may give a key to a value that had
    none, never move one.
    """

    spelled = _LETTER_PREFIX_SEPARATOR.sub(r"\1", _DOCUMENT_NUMBER_SEPARATOR.sub("-", _folded_text(value)))
    head, dash, sequence = spelled.rpartition("-")
    if not dash or not sequence.isdigit():
        return None
    tail = _unpadded_sequence(sequence)
    spellings = (f"{head}-{tail.zfill(width)}" for width in range(len(tail), max(len(tail), _WIDEST_SEQUENCE) + 1))
    if not any(
        is_federal_register_document_number(spelling, column_licensed=True) or _FR_DOCUMENT.fullmatch(spelling)
        for spelling in spellings
    ):
        return None
    return f"{head}-{tail}"


# --------------------------------------------------------------------------- #
# The Federal Register document-number spelling the joins share.
#
# Two public entry points -- the strict join's
# ``normalize_fr_doc_num`` (spicy_docs.sources.sec_comments.join) and
# :func:`unpadded_federal_register_document_number` above -- normalize the
# same family of spellings and must never drift apart, so the mechanical
# rules live here once: the measured en-dash fold
# (:func:`hyphenate_fr_doc_num`), the zero-padding rule
# (:func:`_unpadded_sequence`), the C/R year segment's last-dash-only
# handling (``rpartition``), and the measured C7 -> Z7 mirror series
# (:func:`fr_doc_num_mirror_series`). Each entry point keeps its own grammar
# admission, error contract and fold width: ``unpadded_...`` admits the
# module's forms and folds every dash spelling (:func:`_folded_text`) and the
# separators Regulations.gov types around the hyphen, while the strict join
# admits its own ``_DOC_NUM`` grammar and folds only the measured en dash,
# refusing spellings it has not measured. The separator fold was measured on
# the rulemaking inputs, not on the SEC comments mirror, so it stays the
# key's alone.
#
# What cannot be normalized is documented, not guessed. The mirror's five
# truncated spellings -- ``C1-2017-11``, ``C1-2018-03``, ``C1-2018-08``,
# ``C1-2019-09``, ``C1-2021-16`` -- are readable document numbers the Federal
# Register never served under those spellings: the mirror dropped trailing
# digits of the ``C1-YYYY-NNNNN`` numbers the Register did serve
# (``C1-2017-11151`` and siblings). Truncation is lossy, so no normalization
# recovers them; the SEC comments join bridges them with its title + date
# fallback tier instead.

#: The dash spelling the two document-number corpora were measured to disagree on: the
#: mirror typed an en dash (``E8–27139``) where the Federal Register release hyphenated
#: (``E8-27139``). It is one of :data:`_DASHES`' seven folds; the strict document-number
#: normalizers fold only this one, refusing the spellings they have not measured.
_FR_DOC_EN_DASH = "\u2013"


def hyphenate_fr_doc_num(value: str) -> str:
    """The measured en dash folded to the hyphen the Register uses: ``E8–27139`` -> ``E8-27139``."""

    return value.replace(_FR_DOC_EN_DASH, "-")


#: The mirror's C7 series spelling the Register served as Z7: the tail is exactly the unpadded
#: five-digit form, so the mirror's padded C7 corrections (``C7-01476`` for ``C7-1476``) never fire it.
#: (Not named ``_FR_*``: the ``_FR_`` census in the tests partitions the document-number *forms*,
#: and this is a series remap, not a form.)
_C7_MIRROR_SERIES = re.compile(r"C7-([1-9]\d{4})")


def fr_doc_num_mirror_series(value: str) -> str:
    """The Register spelling of the mirror's C7 PRA series, or the value unchanged.

    Measured 2026-09-24 over the retained releases: regulations.gov spelled the two
    2007 SEC PRA notices ``C7-14563`` and ``C7-15181`` where the Federal Register spelled
    ``Z7-14563`` and ``Z7-15181`` (same dates, same titles). The remap fires only for the
    C7 series' unpadded five-digit tail -- never C -> Z in general, and never the mirror's
    padded C7 corrections (``C7-01476`` -> ``C7-1476``), which the Register does serve
    under C7. The Register's own C7-* column holds only 2007-08 corrections with one- to
    four-digit tails, so no Register-side key changes (measured, same date).
    """

    match = _C7_MIRROR_SERIES.fullmatch(value)
    return f"Z7-{match[1]}" if match is not None else value


def fr_doc_num_release_spelling(value: str) -> str:
    """The Federal Register release's spelling of one admitted document number.

    The spelling mechanics only -- grammar admission is the caller's: the measured
    en dash folds to a hyphen, the mirror's C7 series remaps to Z7, and the final
    sequence loses its zero padding (``2010-00239`` -> ``2010-239``;
    ``C1-2013-00201`` -> ``C1-2013-201`` -- the C/R year segment never moves).
    Raises ``ValueError`` when the final segment is not all digits.
    """

    head, dash, sequence = fr_doc_num_mirror_series(hyphenate_fr_doc_num(value)).rpartition("-")
    if not dash or not sequence.isdigit():
        raise ValueError(f"not a dash-final document number spelling: {value!r}")
    return f"{head}-{_unpadded_sequence(sequence)}"


def normalize_regsgov_identifier(identifier: object) -> str | None:
    """The canonical Regulations.gov identifier, when syntax permits one."""

    value = _folded_text(identifier)
    return value if _REGSGOV_VALID.fullmatch(value) else None


def _behind_the_docket_label(text: str) -> str:
    """What is left when a leading docket label is taken off the front."""

    return _DOCKET_LABEL_PREFIX.sub("", text, count=1).strip()


def docket_reference_as_stated(reference: object) -> str:
    """The reference text a source states, or ``""`` when it states none.

    The source's own characters come back unfolded — this reports what was
    written, it does not normalize it.

    Three kinds of value state nothing: an empty one, the sentinel a
    stringified null leaves behind, and a bare label — "Docket No." with
    nothing behind it is presentation with nothing to present. A value the
    scheme can already express is never read as a label.
    """

    text = _stated_text(reference)
    if text in _UNSTATED_SENTINELS:
        return ""
    if normalize_regsgov_identifier(text) is not None:
        return text
    return text if _behind_the_docket_label(text) else ""


def normalize_docket_reference(reference: object) -> str | None:
    """The Regulations.gov docket identifier a reference states, if any.

    Strip-then-validate, in that order only: a value that is already a
    well-formed identifier is returned untouched, and a stripped remainder
    must open on a letter and carry the organization-year-sequence shape, or
    the label was numbering something that is not a docket.
    """

    stated = docket_reference_as_stated(reference)
    if not stated:
        return None
    for candidate in (stated, _behind_the_docket_label(stated)):
        identifier = normalize_regsgov_identifier(candidate)
        if identifier is None or not _has_regsgov_docket_shape(identifier):
            continue
        # A FERC docket fits the organization-year-sequence shape and is not
        # one of these dockets; regulations.gov calls it malformed.
        if _FERC_DOCKET.fullmatch(identifier):
            return None
        return identifier
    return None


#: What may stand in front of the dockets a docket column names, wider than
#: the single reader's label because this reader then insists the remainder
#: OPEN on a docket: up to three words ("U.S. DOT", "Waiver Petition") before
#: a docket, document or FDMS noun and up to two counter words ("Docket ID
#: Number:", "Docket ID.", "Document Number", "FDMS No."), or a counter word
#: alone ("No. CPSC-2010-0022"), or the conjunction a list split across two
#: values leaves behind ("and FDA-2015-N-1837"). An opening bracket the
#: publisher's page left behind may stand before or after the label
#: ("[Docket No. X", "Docket ID: [X").
_REFERENCES_LEAD = re.compile(
    rf"^[\s\[]*(?:(?:[A-Za-z.]+\s+){{0,3}}?(?:dockets?|docs?|documents?|fdms)\b\.?\s*(?:{_LABEL_COUNTER_WORD}\s*){{0,2}}"
    rf"|{_LABEL_COUNTER_WORD}|and\b|or\b)?[\s:#.\-\[]*",
    re.IGNORECASE,
)
#: One whole token: letters, digits, hyphens and underscores, opening and
#: closing on a letter or digit.
_REFERENCE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?")
#: Where a docket may end in a reference that says more: the end, the
#: punctuation that opens a note ("X, Notice No. 2", "X (HM-224F)", "X:
#: FRL..."), an ampersand that continues a list ("X & Y"), a stray hyphen
#: before one ("EPA-R06-RCRA-2008-0756-"), or a space before a WORD ("X
#: Directorate Identifier ..."). A space before a number is not an end:
#: "WO-150-1820-00 1A" is one Bureau of Land Management serial, not a docket
#: with a note.
_REFERENCE_TOKEN_END = re.compile(r"$|[,;:()\[\]&]|-(?:\s|$)|\s+(?=[A-Za-z(\[&]|$)")
#: The joint between two dockets of one list: "X and Y", "X, Y", "X, Y, and Z", "X; Y", "X & Y".
#: Matched right after a token, so the look-behind reads "a space before the
#: conjunction" as ``\s+and`` did, without a second run of spaces to try
#: against the first: that pair was quadratic in a long run of them.
_REFERENCE_LIST_JOINT = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|;\s*|&\s*|(?<=\s)(?:and|or)\s+)", re.IGNORECASE)
#: "formerly" and what it introduces: an identifier the proceeding no longer
#: goes by ("FDA-2020-N-1253 (formerly FDA-1987-N-0054)", "(formerly part of
#: Docket No. FDA-1975-N-0012)"). In running text that is the first token
#: after the word that carries a digit, docket-shaped or not ("(formerly
#: 81N-0393), FDA-1981-N-0248"): ``\D*`` ends at that digit.
_FORMERLY = re.compile(r"\bformerly\b\D*", re.IGNORECASE)
#: Inside parentheses the whole rest of the parenthetical is the old names
#: ("(Formerly Docket Nos. D01-05-094 and Docket No. USCG-01-06-052)").
_FORMERLY_IN_PARENTHESES = re.compile(r"\([^()]*?(?P<former>\bformerly\b[^()]*)", re.IGNORECASE)
#: The rest of a token from any character inside it.
_TOKEN_REST = re.compile(r"[A-Za-z0-9_-]*")
#: A label that counts something: one to three words, then the counter word
#: that numbers what follows ("File No.", "Summary Notice No.", "Document
#: Identifier", "Funding Announcement Number:", "CIS No."). The words are
#: bounded so the scan stays linear in the value.
_COUNTED_LABEL = re.compile(
    rf"\b(?P<words>(?:[A-Za-z][A-Za-z.']*\s+){{1,3}}?)(?:{_LABEL_COUNTER_WORD}|identifiers?\b)[\s:#.\-]*",
    re.IGNORECASE,
)
#: A docket noun among a counted label's words makes it a docket's label
#: ("Docket FAA No.", "E-Docket ID No.", "eDocket Number", "Dkt. No.").
_DOCKET_NOUN = re.compile(r"(?:\be-?|\b)(?:dockets?|docs?|dkt)\b", re.IGNORECASE)
#: What a label numbers: its first token and the tokens one space joins to it
#: ("File No. SR-LCH SA-2017-006"), up to punctuation, a conjunction or a
#: docket noun.
_LABELLED_NUMBER = re.compile(r"[^\s,;:()\[\]&]+(?:\s(?!(?:and|or|dockets?|docs?)\b)[^\s,;:()\[\]&]+)*", re.IGNORECASE)


def _organization(docket: str) -> str:
    return re.split(r"[-_]", docket, maxsplit=1)[0]


def _outside(spans: list[tuple[int, int]], readings: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The readings that start inside none of the spans; both lists in ascending start order, one pass."""

    kept: list[tuple[int, str]] = []
    spans_left = iter(spans)
    span = next(spans_left, None)
    reach = -1
    for start, docket in readings:
        while span is not None and span[0] <= start:
            reach = max(reach, span[1])
            span = next(spans_left, None)
        if start >= reach:
            kept.append((start, docket))
    return kept


def _walked_list(stated: str) -> tuple[list[tuple[int, str]], int]:
    """The dockets a value opens on, across list punctuation, and where the last one ended (0 for none).

    Each is the single reader's answer for one whole token, so the FERC fence
    and the column's looser shape hold here: after a label, a note ("X, Notice
    No. 2", "X (HM-224F)") or a list ("Docket Nos. X and Y", "X & Y"). A
    member after the first must share the first one's organization or carry
    the prose reader's strict four-digit-year shape, so the numbers a note
    carries ("FRL-8231-8", "SC-20-326", "NIOSH-314") end the list.
    """

    position = _REFERENCES_LEAD.match(stated).end()
    found: list[tuple[int, str]] = []
    walked_to = 0
    while (token := _REFERENCE_TOKEN.match(stated, position)) is not None and _REFERENCE_TOKEN_END.match(
        stated, token.end()
    ):
        docket = normalize_docket_reference(token.group(0))
        if docket is None:
            break
        if found and _organization(docket) != _organization(found[0][1]) and not _DOCKET_BARE.fullmatch(docket):
            break
        found.append((token.start(), docket))
        walked_to = token.end()
        joint = _REFERENCE_LIST_JOINT.match(stated, token.end())
        if joint is None:
            break
        position = joint.end()
    return found, walked_to


def _numbered_by_other_labels(text: str) -> list[tuple[int, int]]:
    """What another system's label numbers, in order: its number, and the list of its organization's after it.

    "File Nos. SR-ISE-2009-04, SR-CBOE-2009-001" is two exchange file numbers,
    and "CIS No. 2295-03 and DHS-2004-0009" is one CIS number and a docket. A
    label inside a span already found is passed over, so the scan is linear.
    """

    spans: list[tuple[int, int]] = []
    position = 0
    while (label := _COUNTED_LABEL.search(text, position)) is not None:
        position = label.end()
        if _DOCKET_NOUN.search(label.group("words")) or (number := _LABELLED_NUMBER.match(text, position)) is None:
            continue
        organization = _organization(number.group(0)).upper()
        end = number.end()
        while (
            (joint := _REFERENCE_LIST_JOINT.match(text, end)) is not None
            and (member := _LABELLED_NUMBER.match(text, joint.end())) is not None
            and _organization(member.group(0)).upper() == organization
        ):
            end = member.end()
        spans.append((number.start(), end))
        position = end
    return spans


#: :data:`_DOCKET_LABELED` with its label opening a token. The prose
#: pattern's ``\b`` also starts inside a hyphenated token, and a failed
#: attempt from each such start rescans the rest of it, quadratic in a long
#: one ("doc-doc-..."); from a token's start there is one attempt per token.
_DOCKET_LABELED_TOKEN = re.compile(
    rf"{_LEFT}{_DOCKET_LABEL}(?P<value>{_docket_body(_DOCKET_YEAR_LICENSED, office=_DOCKET_OFFICE)}){_RIGHT}",
    re.IGNORECASE,
)


def _read_in_prose(text: str, start: int) -> list[tuple[int, str]]:
    """The dockets the prose reader's grammar reads in ``text`` from ``start``, less other labels' numbers.

    A bare reading behind another system's label is that system's number
    ("File No. SR-Amex-2003-102"); a docket label's reading is a docket's.
    """

    # A docket value ends where its token does, so a labelled and a bare
    # reading of one token share an end, and the labelled one is kept: the
    # label says where the identifier begins ("Docket ID-OSHA-2007-0066" is
    # OSHA-2007-0066, not ID-OSHA-2007-0066). The counter word ends at a word
    # boundary, so no label ends inside the identifier's own first word.
    bare = {match.end("value"): match for match in _DOCKET_BARE.finditer(text, start)}
    labelled = {match.end("value"): match for match in _DOCKET_LABELED_TOKEN.finditer(text, start)}
    unlabelled = [(bare[end].start("value"), bare[end].group("value")) for end in sorted(bare) if end not in labelled]
    if unlabelled:
        unlabelled = _outside(_numbered_by_other_labels(text), unlabelled)
    kept = sorted([*unlabelled, *((match.start("value"), match.group("value")) for match in labelled.values())])
    return [(at, docket) for at, value in kept if (docket := normalize_docket_reference(value)) is not None]


def _former_names(text: str) -> list[tuple[int, int]]:
    """Where the identifiers a proceeding no longer goes by stand, in start order."""

    spans = [match.span("former") for match in _FORMERLY_IN_PARENTHESES.finditer(text)]
    spans.extend((match.start(), _TOKEN_REST.match(text, match.end()).end()) for match in _FORMERLY.finditer(text))
    return sorted(spans)


def normalize_docket_references(reference: object) -> tuple[str, ...]:
    """Every docket-shaped value a docket-column reference names, in order, once each; ``()`` for none.

    Shape, not existence, as every answer here: a value is a candidate to be
    joined against the dockets the publisher holds, and one this reader
    returns may name no held docket (an older DOT docket, another agency's
    number of the same silhouette).

    :func:`normalize_docket_reference` reads a reference that IS one docket,
    whole. A docket column also writes a docket inside more: a longer label
    ("U.S. DOT Docket Number X", "Docket ID Number: X"), a note after it ("X,
    Notice No. 2", "X (HM-224F)", "X, FRL-8231-8"), a list ("Docket Nos. X
    and Y", "X & Y"), or prose in front of it ("FAR Case 2017-014, Docket No.
    X", "CIS No. 2295-03 and X", "Public Notice: X", "HHS/X", "X/RIN
    2060-AP50"). The dockets the value opens on are walked first
    (:func:`_walked_list`); the rest of it is prose, and is read with the
    prose reader's own docket grammar, so an unlabelled docket needs the
    four-digit year and a note's numbers ("FRL-8231-8", "SC-20-326",
    "NIOSH-314") are never read. Every reading passes through the single
    reader, so the FERC fence and the shape it states are the same.

    Reading the prose is the owner's ruling of 2026-09-26, and it reverses
    this reader's first rule, "deliberately not a search": a reference that
    only mentions a docket somewhere named none. That rule cost measured
    dockets. Over the rulemaking build's ``fr_docket_links`` (2026-09-23,
    spicy-docs ``docs/research/parsing-survey-2026-09-23.md`` item A7) the
    walk read 5,389 of the 5,825 link rows naming a held docket in full and
    67 in part, and left 369 open on something else; the rulemaking drift
    audit of 2026-09-26 found 442 (FR document, held docket) pairs it missed,
    175 from action documents, and two dockets retired as shells although an
    action notice names them (FAR-2018-0003, DHS-2004-0009). Two fences keep
    what the old rule kept out:

    - **Another system's label numbers what follows it.** Behind a counted
      label without a docket noun ("File No.", "Summary Notice No.",
      "Document Identifier", "CIS No.") a bare docket shape, and a list of its
      organization's, is that system's number. Without the fence the search
      reads 11,572 more values that name no held docket, 11,184 of them
      exchange rule filings ("File No. SR-Amex-2003-102"); it costs 11 pairs
      whose agency writes the docket behind its own label ("DHS No.
      ICEB-2008-0004", "FRA Waiver Petition No. FRA-2000-7054").
    - **A former identifier is not named.** "formerly" fences the first
      identifier after it, and inside parentheses the rest of the
      parenthetical ("X (formerly Y)", "(Formerly Docket Nos. Y and Z)"): 20
      pairs, each a docket the document once went by. One of them the walk
      read, and no longer does: "Formerly Docket FDA-2008-N-0041".

    Measured 2026-09-26 over the audit's 612,342 distinct ``fr_docket_links``
    values against the dockets table (receipt
    ``fork-execution-2026-09-21/drift-qualification-2026-09-26/regulatory/d1d2-fix``):
    506 answers change, 433 values are read that were not (323 naming a held
    docket, 110 naming none), and 465 (FR document, held docket) pairs are
    gained, 421 of the audit's 442 among them. The 21 still missed are the
    label fence's 11, nine dockets with a two-digit year in unlabelled prose
    ("Document No. DA-11-03: AMS-DA-08-0050"), where it is a report number's
    silhouette, and one behind a stray hyphen.
    """

    whole = normalize_docket_reference(reference)
    if whole is not None:
        return (whole,)
    stated = docket_reference_as_stated(reference)
    if not stated:
        return ()
    walked, walked_to = _walked_list(stated)
    readings = [*walked, *_read_in_prose(stated, walked_to)]
    if not readings:
        return ()
    return tuple(dict.fromkeys(docket for _, docket in _outside(_former_names(stated), readings)))


# --------------------------------------------------------------------------- #
# Detection — spans on the original text, overlaps arbitrated.


def keep_longest_then_most_specific(candidates: list[IdentifierCandidate]) -> list[IdentifierCandidate]:
    """Keep the longest claim on any stretch of text, then the most specific.

    The sort states the rule — earliest start, then longest, then most
    specific — and a single exact sweep applies it: claims arrive in
    ascending start order, so the furthest end reached is the only thing a
    new claim can collide with.
    """

    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.span[0],
            -(candidate.span[1] - candidate.span[0]),
            _KIND_PRECEDENCE.index(candidate.kind),
        ),
    )
    kept: list[IdentifierCandidate] = []
    reach = 0
    for candidate in ordered:
        start, end = candidate.span
        if start < reach:
            continue
        kept.append(candidate)
        reach = max(reach, end)
    return kept


#: Every grammar the prose reader runs, with the component names each one
#: reports. All five wrap the identifier in a ``value`` group, so one loop
#: reads them: the span is the group's span, which is what keeps a docket
#: label out of the identifier it labels.
#:
#: A name here is what the grammar *may* state, not what it always states:
#: ``office`` is optional, and an optional segment nobody stated is absent
#: from the components rather than present and empty.
_DETECTORS: tuple[tuple[IdentifierKind, re.Pattern[str], tuple[str, ...]], ...] = (
    (IdentifierKind.RIN, _RIN, ()),
    (IdentifierKind.FEDERAL_REGISTER_DOCUMENT, _FR_DOCUMENT, ()),
    (
        IdentifierKind.REGULATIONS_GOV_DOCUMENT,
        _REGULATIONS_GOV_DOCUMENT,
        ("organization", "year", "office", "docket_sequence", "segment", "document_sequence"),
    ),
    (IdentifierKind.DOCKET, _DOCKET_BARE, ("organization", "year", "office", "sequence", "segment")),
    (IdentifierKind.DOCKET, _DOCKET_LABELED, ("organization", "year", "office", "sequence", "segment")),
)


def _in_slash_token(text: str, start: int, end: int) -> bool:
    """A slash makes this a compound identifier or URL, not a bare RIN.

    GSA prospectus numbers such as ``PMD-0778/1822-MD20`` contain a RIN-shaped
    suffix. Inspect the whole whitespace-delimited token, including any URL
    punctuation, without rescanning the document for each candidate.
    """
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return "/" in text[start:end]


def detect_identifier_shapes(text: str | None) -> list[IdentifierCandidate]:
    """Every catalog identifier a text names, longest-claim-wins.

    Detection is pure and reads the normalized-dash text, but every span
    indexes the original. Citation kinds (CFR, U.S.C., …) are
    :mod:`spicy_docs.interpretation.citation_grammar`'s job; compose the two modules
    for a full scan.

    Two grammars can name the identical identifier — a docket written behind
    a label is claimed by the labelled and the bare pattern alike — so
    identical claims are collapsed before the overlap sweep, which arbitrates
    between *different* claims and would otherwise see a tie where there is
    only one identifier.
    """

    if not text:
        return []
    normalized = text.translate(_DASHES)

    seen: set[IdentifierCandidate] = set()
    found: list[IdentifierCandidate] = []
    for kind, pattern, components in _DETECTORS:
        for match in pattern.finditer(normalized):
            if kind is IdentifierKind.RIN and _in_slash_token(normalized, *match.span("value")):
                continue
            candidate = IdentifierCandidate(
                kind=kind,
                value=match.group("value").upper(),
                span=match.span("value"),
                components={name: match.group(name).upper() for name in components if match.group(name) is not None},
            )
            if candidate not in seen:
                seen.add(candidate)
                found.append(candidate)
    return keep_longest_then_most_specific(found)
