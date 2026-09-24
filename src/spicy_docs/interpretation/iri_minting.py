"""The minting layer: shapes in, one canonical ``urn:rkaf`` identifier out.

:mod:`identifier_shapes` named the hole this module fills until 2026-09-04:
*"IRI minting (``urn:rkaf:...``) stays with consumers until the minting layer
is its own port."* It wraps the shape layer's existing validators
(:func:`~identifier_shapes.normalize_rin`,
:func:`~identifier_shapes.normalize_docket_reference`,
:func:`~identifier_shapes.detect_identifier_shapes`, ...) and adds no second
opinion about what a real identifier looks like; where a minter is narrower —
letters-only CFR parts, the ``[0-9]{2}`` RIN tail, the three-digit Federal
Register document floor, a CFR title outside the 50 that exist (reserved 35
included) — the narrowing is rulespec's lexical space and is named at the
site. Minting checks the supported syntax only: never a roster, and never that
a value was actually issued.

The lexical spaces in :data:`IDENTIFIER_SPACES` are restated **verbatim** from
the compiled rulespec profiles in RefSpec's vendored ``rulespec-conformance``
wheel, so what a minter emits is what rulespec's own validators accept.
spicy-docs cannot check that itself: it deliberately does not depend on that
wheel (``tests/releases/test_compatibility.py``), and ``rulespec-artifacts``,
which it does, carries no identifier space. RefSpec's
``test_the_minted_spaces_are_the_contract_verbatim`` holds RefSpec's own copies
true; it holds these once RefSpec imports this module and points that test at
this table (``docs/decisions.md``).

Refusal is ``None``, and a broken invariant raises: a value that states no
identifier is a measured population (39.2% of the pinned Federal Register
``document_number`` column), not an error, so every minter is a total function
returning ``MintedIdentifier | None``. ``ValueError`` is reserved for
:class:`MintedIdentifier` — which refuses to exist outside a declared scheme's
space — and for a caller-asserted ``publication_date`` that is not a date.
Anything the space cannot spell stays identified, never dropped: it takes
rulespec's ``rkaf:partner-defined`` escape hatch under
:func:`mint_partner_iri`, with RefSpec as the partner and the segment
layout copied from rulespec's own fixture
``urn:rkaf:partner:fixture:proceeding:EPA-HQ-OAR-2021-0317``.

:func:`mint_federal_register_document_iri` takes ``column_licensed``, and only
that flag admits :data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`; prose
detection is never loosened. :func:`mint_regulations_gov_docket_iri` wraps a
column reader, so it mints what a ``docket_ids_json`` value states, including
a Regulations.gov document id that fits the docket shape.

Provenance
----------
Moved into spicy-docs on 2026-09-23 beside :mod:`citation_grammar` and
:mod:`identifier_shapes`, whose moved copies it imports. spicy-regs
(``build_regulatory_agenda._agenda_item_id``, ``ontology/citations.py``),
rulespec-projection and spicysearch each carry their own minters, and
spicy-regs decision 28 puts the stack's minters here, beside the shapes, not
in Rulespec Core: spicy-docs is the one place all of them can import. RefSpec's
REF-024, amended 2026-09-24, gives Rulespec Core the lexical spaces and
spicy-docs the minters (``docs/decisions.md``).

The source is RefSpec ``src/refspec/registry/iri_minting.py`` at RefSpec
``4a680c81`` (last changed in ``ef654b59``). With docstrings aside, the code
differs in one seam: the Federal Register collision verdicts it read from
RefSpec's ``hand_validated_interpretations`` are :data:`_FR_COLLISION_VERDICTS`
here, answering the same for every value. Behaviour differs in one place, and
through the shapes rather than this code: since 2026-09-23 the column docket
reader :func:`mint_regulations_gov_docket_iri` wraps also reads a docket ending
in one of the prose reader's ``-RULE``-family tokens (see
:func:`~identifier_shapes.normalize_docket_reference`), which RefSpec's copy
refuses. Over 3,966,225 paired calls (RefSpec's pinned Federal Register and
Unified Agenda columns, every literal in RefSpec's minting, zero-part and shape
tests, and fuzz), the two minters' outputs, ``ValueError`` messages included,
are byte-identical except three dockets minted here and refused there:
``GIPSA-2008-FGIS-0002-NONRULEMAKING``, ``GIPSA-2010-FGIS-0014-NONRULEMAKING``
and ``Docket #GIPSA-2010-FGIS-0014-NONRULEMAKING``, the last the one such value
in the pinned Federal Register ``docket_ids_json``. RefSpec's expectation at
``tests/test_identifier_shapes.py:365``
(``test_a_docket_must_end_on_the_sequence_it_is_keyed_by``) moves when it
adopts this module; with ``tests/test_cfr_ranges.py:106``, a grammar
expectation the same day moved, it is one of only two of the 2,593 RefSpec
tests importing the three moved modules that fail against these copies. The
self-contained tests are ported to ``tests/test_iri_minting.py`` and
``tests/test_cfr_zero_parts.py``; the six that read the conformance wheel,
RefSpec's pinned columns or its hand-validated evidence stay in RefSpec.
``act_resolution``, ``hand_validated_interpretations`` and REF-numbered
decisions are RefSpec's.

Two docstrings were stale at the source and are corrected here, each against
its own test: :func:`_cfr_part` said the grammar still minted the ``41 CFR
101-1`` phantom, which RefSpec ``61bb05d0`` closed, and :func:`mint_cfr_iri`
said part 0 is refused, which RefSpec ``0d7d2f12`` reversed.

Adoption by spicy-regs
----------------------
spicy-regs decision 27 chose the rkaf spaces this module mints into for
Federal Register documents, and the deletion of ``urn:spicy-regs:frdoc``,
having found that no published spicy-regs column carries that prefix. The one
minter that writes it, ``federal_register_identifier``
(``ontology/citations.py``), has no build caller, so adopting this module moves
no published Federal Register value; only the timing of spicy-regs' swap is
open. What the swap changes in that function's output, measured over the
2026-09-23 rulemaking build: of the 1,009,005 ``document_number`` rows,
455,982 mint the same IRI through both, 429,131 move
from ``urn:spicy-regs:frdoc:`` into an rkaf space, 123,522 are respelled
``urn:rkaf:partner:refspec:frdoc:``, and 370 are refused here (8 of them
REF-066 collision rows). The RIN, CFR and executive-order minters agree with
spicy-regs' own on 38,403 RINs, 9,331 CFR references and 1,541 orders,
refusals included, except two RINs spelled with an en dash, which only this
module folds and mints. Receipt:
``~/Work/corpora/fork-execution-2026-09-21/utilization-audit-2026-09-23/refspec/f1/``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from urllib.parse import quote

from spicy_docs.interpretation.citation_grammar import CFR_TITLE_COUNT, states_nothing
from spicy_docs.interpretation.identifier_shapes import (
    _DASHES,  # the shape layer's own table, shared deliberately -- see its docstring
    BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER,
    IdentifierKind,
    detect_identifier_shapes,
    is_federal_register_document_number,
    normalize_docket_reference,
    normalize_rin,
)

__all__ = [
    "BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER",
    "IDENTIFIER_SPACES",
    "PARTNER_NAMESPACE",
    "MintedIdentifier",
    "mint_cfr_iri",
    "mint_executive_order_iri",
    "mint_federal_register_document_iri",
    "mint_partner_iri",
    "mint_public_law_iri",
    "mint_regulations_gov_docket_iri",
    "mint_rin_iri",
]

# --------------------------------------------------------------------------- #
# The contract, restated verbatim.

#: rulespec's lexical spaces, one per scheme this module mints into, restated
#: **verbatim** from the compiled profiles in RefSpec's vendored
#: ``rulespec-conformance`` wheel. Each is stated identically in all four
#: compiled forms — JSON Schema, SHACL, Rego and TypeScript — and RefSpec's
#: ``test_the_minted_spaces_are_the_contract_verbatim`` sweeps the package to
#: hold RefSpec's copies true; it holds these once RefSpec points it at this
#: table (module docstring). Restating rather than reading the package at
#: runtime is deliberate: reading it would make this module agree with
#: whatever shipped rather than with what was reviewed.
#:
#: The one edit to each string is making its groups non-capturing, which the
#: verbatim test undoes before comparing. ``rkaf:partner-defined`` is the
#: exception and says so at :data:`_PARTNER_IRI`: rulespec states no lexical
#: space for it, because the point of the escape hatch is that it has none.
_US_CFR = re.compile(r"^urn:rkaf:us:cfr:[1-9][0-9]*:[0-9]+(?:[a-z]|-[0-9]+)?(?:\.[0-9]+[a-z]{0,3}(?:-[0-9a-z]+)*)?$")
_US_EO = re.compile(r"^urn:rkaf:us:eo:[1-9][0-9]*$")
_US_FRDOC = re.compile(r"^urn:rkaf:us:frdoc:[0-9]{4}-[0-9]{3,5}$")
#: The pre-2010 form, and the only space here whose identity is not the
#: number alone: rulespec qualifies it with the publication date because
#: the bare number does not identify a document -- "00-111" names two, and
#: the parquet reported zero collisions only because it had already dropped
#: one of them. New in rc17; see REF-064.
_US_FRDOC_LEGACY = re.compile(r"^urn:rkaf:us:frdoc-legacy:[0-9]{2}-[0-9]{1,6}:[0-9]{4}-[0-9]{2}-[0-9]{2}$")
#: The X family, and the only Federal Register space that needs no date
#: qualifier because the number already carries one: read RIGHT-ANCHORED,
#: the last four digits are the month and day and everything before them is
#: the sequence, which agrees with the publication date on 4,400 of 4,400
#: corpus rows. That makes a disagreement a DETECTABLE DEFECT rather than
#: the ambiguity the legacy form has. The tail is ``{5,7}`` as capacity, not
#: data fit: a fixed-width ``{5}`` would have refused ``X09-101207`` on its
#: first day, one of 206 six-digit numbers that a five-digit shape had been
#: silently filtering out of its own census. New in rc18; see REF-065.
_US_FRDOC_X = re.compile(r"^urn:rkaf:us:frdoc-x:X[0-9]{2}-[0-9]{5,7}$")
_US_PL = re.compile(r"^urn:rkaf:us:pl:[1-9][0-9]*-[1-9][0-9]*$")
_US_REGSGOV = re.compile(r"^urn:rkaf:us:regsgov:[A-Z0-9]+(?:[-_][A-Z0-9]+)*$")
_US_RIN = re.compile(r"^urn:rkaf:us:rin:[0-9]{4}-[A-Z]{2}[0-9]{2}$")

#: RefSpec, as the partner. The namespace stays ``refspec`` now that the
#: minter lives in spicy-docs: it is spelled into every partner identifier
#: already minted, and a sealed identity does not move with its code.
#: rulespec's own fixtures write a
#: partner-defined identifier as ``urn:rkaf:partner:<namespace>:<kind>:<value>``
#: — ``urn:rkaf:partner:fixture:proceeding:EPA-HQ-OAR-2021-0317`` — so the
#: layout is the publisher's, not an invention, and only the namespace is
#: ours. The archived spicy-regs minter reached for its own URN prefix
#: (``urn:spicy-regs:frdoc:...``) instead, which named nothing rkaf could
#: resolve; naming the partner INSIDE the rkaf URN keeps the escape hatch
#: inside the vocabulary it escapes from.
PARTNER_NAMESPACE = "refspec"

#: A partner ``kind`` is a plain lowercase family word — no colon, no case
#: variant, no leading digit — so a partner identifier always parses back
#: into its five segments unambiguously ("us:usc" as a kind would spell a
#: string that reads as six). What the fence does NOT do is refuse a real
#: family's word: :func:`mint_federal_register_document_iri` deliberately
#: mints kind ``frdoc`` beside the real ``rkaf:us-frdoc`` space, because an
#: unspellable member of a family is still a member of it. The
#: ``urn:rkaf:partner:refspec:`` prefix, not the kind, is what keeps the
#: partner namespace apart from rulespec's own.
_PARTNER_KIND = re.compile(r"[a-z][a-z0-9-]*")

#: The partner space. Its body is whatever :func:`mint_partner_iri`
#: percent-encodes, so the alphabet is RFC 3986's unreserved set plus the
#: escape character — which is also what makes the result satisfy
#: :data:`_RKAF_IDENTIFIER` for free.
_PARTNER_IRI = re.compile(rf"^urn:rkaf:partner:{PARTNER_NAMESPACE}:[a-z][a-z0-9-]*:[A-Za-z0-9._~%-]+$")

#: Scheme -> the space an identifier in it must live in. The scheme names are
#: rulespec's ``#USRegulatoryIdentifierScheme`` / ``#AgendaItemIdentifierScheme``
#: / ``#ArtifactIdentifierScheme`` enum members; a :class:`MintedIdentifier`
#: outside this table cannot be constructed at all. (The RIN enum is
#: ``#AgendaItemIdentifierScheme``, defined at ``rulemaking.cue:11``. This
#: comment used to say ``#RinIdentifierScheme``, which rulespec has never
#: defined.)
IDENTIFIER_SPACES: Mapping[str, re.Pattern[str]] = {
    "rkaf:us-cfr": _US_CFR,
    "rkaf:us-eo": _US_EO,
    "rkaf:us-frdoc": _US_FRDOC,
    "rkaf:us-frdoc-legacy": _US_FRDOC_LEGACY,
    "rkaf:us-frdoc-x": _US_FRDOC_X,
    "rkaf:us-pl": _US_PL,
    "rkaf:us-regsgov": _US_REGSGOV,
    "rkaf:us-rin": _US_RIN,
    "rkaf:partner-defined": _PARTNER_IRI,
}

#: What rkaf requires of ANY identifier, whatever its scheme:
#: ``rkaf:hasArtifactIdentifier`` and ``rkaf:hasRegulatoryIdentifier`` are both
#: constrained to this in every compiled profile. It is the floor every space
#: above sits on, checked separately so a future space cannot be added that
#: satisfies itself and not the floor — the structural check the U.S.C.
#: precedent's family would apply to anything claiming to be one of these.
_RKAF_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


# --------------------------------------------------------------------------- #
# The Federal Register's bare-legacy document number.
#
# MOVED HOME 2026-08-31 (REF-052): the shape, its evidence, and the dash-fold
# table this module used to mirror all now live in
# ``identifier_shapes.BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`` and
# ``identifier_shapes._DASHES``, imported above rather than restated. That
# module is content-hashed into a build receipt, which is why the shape lived
# here instead until this cycle's rebuild unit. Nothing about what this
# module MINTS changes: ``mint_federal_register_document_iri``'s
# ``column_licensed`` flag reads the identical shape it read before, now
# through :func:`~identifier_shapes.is_federal_register_document_number`
# rather than a local pattern.


# --------------------------------------------------------------------------- #
# The Federal Register collision verdicts (REF-066).

#: The seven modern-form document numbers RefSpec's 2026-09-02 full crawl of
#: the Federal Register found carrying two publication dates each, and the
#: disposition a reading of both documents gave each one. ``refusal-to-interpret``:
#: two unrelated documents share the number, so one identifier would merge
#: them. ``consulted``: a notice and its own correction, so one identifier is
#: right. Both halves are kept so the two cannot be "helpfully" refused.
#:
#: The verdicts are RefSpec's ``hand_validated_interpretations._FR_COLLISION_TABLE``
#: rows, restated here because spicy-docs cannot import RefSpec. The evidence
#: stays there: the census pinned at
#: ``sha256:427a68272f87225e45c7bc25376c73c2761e07a613c7d87a8a6cdaa73c73356c``
#: in ``research/evidence/fr-collision-census-2026-09-02/``, the two dated
#: captures witnessing each row, and the audit holding the rows to both.
#: RefSpec's own predicate answers from those literal rows too, re-checking the
#: evidence first where a checkout has it and raising on drift, so this table
#: gives its answer for every value. Nothing here can compare the two tables;
#: RefSpec does once it imports this module (``docs/decisions.md``). A
#: re-crawl's eighth collision lands in RefSpec's evidence first and must be
#: carried here.
_FR_COLLISION_VERDICTS: Mapping[str, str] = MappingProxyType(
    {
        "2010-31094": "refusal-to-interpret",
        "2010-31384": "refusal-to-interpret",
        "2010-31396": "refusal-to-interpret",
        "2010-31415": "refusal-to-interpret",
        "2010-517": "refusal-to-interpret",
        "2015-17759": "consulted",
        "2015-25354": "consulted",
    }
)


def is_a_refused_federal_register_collision(document_number: str) -> bool:
    """Whether ``document_number`` names two documents, so no identifier may stand for it.

    One dict lookup against :data:`_FR_COLLISION_VERDICTS`: an ordinary number
    reaches no file, no census and no git, which is the property REF-066's
    2026-09-02 audit required of every mint. The name and the module-level seam
    are RefSpec's, so a caller that replaces the predicate still replaces what
    :func:`mint_federal_register_document_iri` consults.
    """

    return _FR_COLLISION_VERDICTS.get(document_number) == "refusal-to-interpret"


# --------------------------------------------------------------------------- #
# The minted value.


@dataclass(frozen=True)
class MintedIdentifier:
    """One identifier, and the rulespec scheme whose space it satisfies.

    Both halves, because rulespec requires both: an artifact carrying
    ``rkaf:hasRegulatoryIdentifier`` is invalid without
    ``rkaf:regulatoryIdentifierScheme`` beside it, and the scheme is precisely
    what differs between a Federal Register number rkaf can spell and one it
    cannot. A minter that returned the IRI alone would make every consumer
    re-derive the half that carries the news.

    Constructing one outside a declared scheme's space raises, and that is the
    module's whole structural guarantee: no minter can emit an identifier
    rulespec's validators would reject, because the type will not hold one.
    """

    scheme: str
    iri: str

    def __post_init__(self) -> None:
        space = IDENTIFIER_SPACES.get(self.scheme)
        if space is None:
            raise ValueError(f"undeclared identifier scheme: {self.scheme!r}")
        if not space.fullmatch(self.iri):
            raise ValueError(f"{self.iri!r} is outside the lexical space of {self.scheme}")
        if not _RKAF_IDENTIFIER.fullmatch(self.iri):
            raise ValueError(f"{self.iri!r} is not a well-formed rkaf identifier")


def _mint(scheme: str, iri: str) -> MintedIdentifier | None:
    """The candidate, or ``None`` when the contract will not hold it.

    The one place the two conventions meet: the type raises because a
    malformed pair is a broken invariant, and a minter refuses because a value
    outside a space is data. Written once so no minter restates the space
    check that :class:`MintedIdentifier` already performs.
    """

    try:
        return MintedIdentifier(scheme=scheme, iri=iri)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Spelling helpers. Selecting and folding only -- never inventing.


def _stated(value: object) -> str:
    """The characters a value states, stripped. Only ``None`` states nothing.

    Mirrors ``identifier_shapes._stated_text``, including its reason: one
    coercion, so two readers cannot disagree about the same value.
    ``str(value or "")`` made the falsy integer 0 state nothing.
    """

    return "" if value is None else str(value).strip()


def _positive_integer(value: object) -> str | None:
    """The canonical decimal a value states, or ``None``.

    A leading zero is spelling, not identity, and stripping it is the
    ``citation_grammar._canonical_part`` rule — "the part is a JOIN KEY, and
    '0718' must meet '718'" — applied wherever rulespec writes an integer
    production. The Unified Agenda's filers pad: 95 of its CFR titles are
    written "07 CFR 1943", and every one is USDA's title 7.

    ``[0-9]`` rather than ``str.isdigit``: that predicate is true of Unicode
    digits, and ``int("٧")`` is 7, which would let a minter emit an identifier
    no publisher wrote.
    """

    text = _stated(value)
    if re.fullmatch(r"[0-9]+", text) is None:
        return None
    return text.lstrip("0") or None


def _cfr_part(value: object) -> str | None:
    """A CFR part: the canonical decimal, optionally one lowercased letter.

    ``rkaf:us-cfr`` writes the part as ``[0-9]+([a-z]|-[0-9]+)?``, and this
    helper is deliberately narrower than that: it mints the numeric and
    single-letter forms and REFUSES the hyphen-number form. The narrowing is
    the same kind :func:`mint_cfr_iri` already makes against the title, and it
    is named here rather than left to be discovered.

    **The letter branch.** ``[a-z]`` was 83 of the OFR index's 272 non-numeric
    parts, and it has a live producer: ``parse_cfr_citations("7 CFR 15a")``
    returns part ``15a`` today. Four parts are published UPPERCASE — 26 CFR
    16A, 29 CFR 4022B, 29 CFR 4041A, 46 CFR 147A — and the prose reader emits
    the uppercase spelling verbatim, so folding here is the only thing that
    makes them mintable. The fold is lossless: no part collides with another
    under it anywhere in the index, and each of those four titles also has the
    bare numeric part (26 CFR 16, 29 CFR 4022, ...), which is why the rule is
    to fold and never to truncate.

    **The hyphen branch, refused.** The other 189 non-numeric parts are
    hyphen-numbered (41 CFR 101-1), and every single one is in title 41.
    Elsewhere a hyphen after a part number means a range (40 CFR 60-63), a
    section written loosely (28 CFR 23-4 for §23.4) or a numbered standard
    (49 CFR 571-108) — none of them a part. The space carries the hyphen form;
    this minter does not, because no pinned column carries a hyphen part
    (REF-054: 852 distinct ``cfr_part`` values, all numeric).

    The phantom REF-054 deferred is closed on the grammar's side. The capture
    used to stop at the hyphen, so ``parse_cfr_citations("41 CFR 101-1")``
    yielded part ``101`` and this function minted ``urn:rkaf:us:cfr:41:101``,
    a part that does not exist — none of title 41's 16 hyphen heads is a part
    in its own right. Since RefSpec ``61bb05d0`` ``_CFR_PART_CAPTURE`` takes
    the whole token: title 41 yields part ``101-1``, which this function
    refuses, and any other title yields no part at all. Neither mints a
    shorter numeric prefix.

    Unlike titles, parts can be zero: the publisher XML includes 16 CFR part 0
    (Organization), among others. Strip padding while preserving a zero stem;
    minting a supported spelling does not establish issuance or applicability.
    """

    text = _stated(value).lower()
    match = re.fullmatch(r"([0-9]+)([a-z]?)", text)
    if match is None:
        return None
    number = match[1].lstrip("0") or "0"
    return f"{number}{match[2]}"


def _cfr_section(value: object) -> str | None:
    """A CFR section suffix, lowercased, with subsection detail dropped.

    A parenthetical is DROPPED rather than refused, so "60.18(a)" resolves to
    the section that contains it — the deliberate narrowing
    RefSpec's ``act_resolution.canonical_usc_iri`` makes and pins one column over. A
    section this cannot spell inside rulespec's production is refused, never
    truncated to the part.
    """

    text = re.sub(r"\([^)]*\)", "", _stated(value).lower())
    return text if re.fullmatch(r"[0-9]+[a-z]{0,3}(?:-[0-9a-z]+)*", text) else None


def _states_a_federal_register_document(text: str) -> bool:
    """Whether the shape layer reads the whole value as one FR document number.

    The prose reader's four recognised forms — modern, correction,
    republication and legacy — asked as one question, so this module admits
    exactly what :mod:`identifier_shapes` admits and never a form of its own.
    "Whole" matters: a value that merely CONTAINS a document number states a
    sentence, not an identifier, and 56,364 "Not Assigned" strings are what a
    containment test buys.
    """

    candidates = detect_identifier_shapes(text)
    return (
        len(candidates) == 1
        and candidates[0].kind is IdentifierKind.FEDERAL_REGISTER_DOCUMENT
        and candidates[0].span == (0, len(text))
    )


# --------------------------------------------------------------------------- #
# The seven minters.


def mint_cfr_iri(title: object, part: object, section: object = None) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:cfr:{title}:{part}[.{section}]``.

    The title is fenced to the 50 that exist (:data:`CFR_TITLE_COUNT`),
    reserved title 35 included — it held the Panama Canal until 2000, so a
    1990s citation to it is real. This is the one place a minter is narrower
    than the grammar on purpose: ``parse_cfr_citations`` keeps an impossible
    title with a false ``title_is_possible`` verdict, because a data-quality
    consumer needs the row, while minting an identifier for a title that does
    not exist would publish the claim rather than the doubt.

    Mints a LETTERED part, folding its suffix to lowercase, and refuses a
    hyphen-number part — both decided in :func:`_cfr_part`, which carries the
    measurements and the reason the second is a deliberate narrowing against
    the space rather than an oversight. "7 CFR 15" and "7 CFR 15a" stay
    separate identifiers, as they are separate parts.

    Refuses title 0, which rulespec's own title production already refuses,
    but mints part 0: the publisher prints it (16 CFR part 0, Organization),
    and :func:`_cfr_part` keeps a zero stem.

    A section that STATES NOTHING is no section, not a bad one: a
    ``cfr_section`` column carrying "", "None" or "N/A"
    (``citation_grammar.states_nothing``, whose sentinel set the Agenda's own
    placeholders bought) mints the part, where refusing the whole citation
    would throw away the half the source did state.
    """

    title_text = _positive_integer(title)
    if title_text is None or not 1 <= int(title_text) <= CFR_TITLE_COUNT:
        return None
    part_text = _cfr_part(part)
    if part_text is None:
        return None
    body = f"{title_text}:{part_text}"
    if not states_nothing(section):
        section_text = _cfr_section(section)
        if section_text is None:
            return None
        body = f"{body}.{section_text}"
    return _mint("rkaf:us-cfr", f"urn:rkaf:us:cfr:{body}")


def mint_executive_order_iri(number: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:eo:{number}``.

    Deliberately NOT fenced by ``citation_grammar.EO_HIGHEST_KNOWN``. That
    bound is a dated fact for builders judging pinned captures — the module
    that states it says so — and a minter that refused above it would refuse
    the next order the President signs. The series has one real floor, that it
    starts at 1, and rulespec's ``[1-9][0-9]*`` already states it.
    """

    text = _positive_integer(number)
    return None if text is None else _mint("rkaf:us-eo", f"urn:rkaf:us:eo:{text}")


def mint_rin_iri(value: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:rin:{rin}`` for a Regulation Identifier Number.

    Wraps :func:`~identifier_shapes.normalize_rin`, which answers "is this
    string one" and never "does it contain one" — 56,364 of 64,537 catalog
    ``rin`` values are the literal string "Not Assigned", and a containment
    test made it the corpus's most common identifier by a factor of ten.

    ``rkaf:us-rin`` closes on ``[0-9]{2}`` where the shape allows
    ``[A-Za-z0-9]{2}``, so a RIN whose last two characters are letters
    normalizes and then refuses. None of the 46,547 Unified Agenda RINs
    measured on 2026-08-31 took that form. REF-054 retained this supported
    space; the cited Fish and Wildlife Service format statement is
    agency-specific, not a universal grammar.

    The five historically documented published exceptions (0648-XD990,
    0648-XC705, 3090-00XX, 1115-09AE, 2070-78AB) remain outside the space:
    two have five-character tails, three have digit-digit-letter-letter
    tails. This function checks syntax only. ``None`` does not prove a
    RIN does not exist, and success does not prove issuance or source meaning.
    """

    rin = normalize_rin(value)
    return None if rin is None else _mint("rkaf:us-rin", f"urn:rkaf:us:rin:{rin}")


def mint_regulations_gov_docket_iri(reference: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:regsgov:{docket}`` for a Regulations.gov docket.

    Wraps :func:`~identifier_shapes.normalize_docket_reference` whole, which
    carries three rules this module must not restate: strip-then-validate in
    that order only (so Commerce's own ``DOC-2010-0001`` is not mutilated by
    the label grammar), a stripped remainder that must open on a letter (which
    refuses 5,214 of 5,506 mutilated references and costs no real docket), and
    the FERC exclusion (24,548 references of the "CP26-20-000" form fit the
    shape and belong to another registry).

    It is a COLUMN reader, and inherits that license exactly: the wrapped
    shape absorbs "EPA-HQ-OAR-2021-0317-0001" — a Regulations.gov *document*
    id — and mints it as a docket, because a value arriving from
    ``docket_ids_json`` is a docket by the field's own declaration. The prose
    reader arbitrates the identical characters the other way, and that
    arbitration is where the question belongs; a caller holding a document id
    must not hand it to a docket minter.
    ``test_the_docket_minter_inherits_the_column_readers_license`` pins both
    halves, because either one changing silently is how a document id becomes
    a docket downstream.
    """

    docket = normalize_docket_reference(reference)
    return None if docket is None else _mint("rkaf:us-regsgov", f"urn:rkaf:us:regsgov:{docket}")


def mint_public_law_iri(public_law: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:pl:{congress}-{number}`` from "119-101".

    Takes the compound the grammar already produces —
    ``AuthorityCitation.public_law`` is written
    ``f"{int(congress)}-{int(number)}"`` — so the label spellings, the doubled
    dash and the dotted separator are read where they are read today and this
    layer never re-parses prose.

    Deliberately NOT fenced by ``PL_FIRST_NUMBERED_CONGRESS`` or
    ``CONGRESS_CURRENT``, for the reason those constants give themselves: they
    are dated series bounds for damage detection, and the next Congress
    outruns them. Minting for the 120th Congress must work the day it sits.
    """

    text = _stated(public_law).translate(_DASHES)
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", text)
    if match is None:
        return None
    congress, number = _positive_integer(match[1]), _positive_integer(match[2])
    if congress is None or number is None:
        return None
    return _mint("rkaf:us-pl", f"urn:rkaf:us:pl:{congress}-{number}")


def _publication_day(publication_date: object) -> str:
    """``YYYY-MM-DD`` for a date a caller ASSERTED, or a raised error.

    The one place this module raises on a parameter rather than answering
    ``None`` about data, and the distinction is the module's own: a value that
    is not a Federal Register document number is DATA and gets a refusal, while
    a caller who passes ``publication_date="not a date"`` has asserted a fact
    that is not one, which is a broken invariant of the call. Downgrading it
    silently to ``rkaf:partner-defined`` would publish an identity missing
    exactly the qualifier the caller believed it supplied -- the failure a
    date-qualified space exists to prevent. So it is loud, the same way
    :class:`MintedIdentifier` is loud about a space violation.

    Accepts anything that spells an ISO day: ``datetime.date``,
    ``"2009-08-19"``, and the ``date32`` a PyArrow column yields, which is what
    the corpus actually hands a caller. A datetime is refused rather than
    truncated -- an identity is not the place to drop a time silently.
    """

    if isinstance(publication_date, datetime):
        # ValueError, not TypeError, is the contract: every asserted date that is not a day raises one error.
        raise ValueError(f"publication_date must name a day, not an instant: {publication_date!r}")  # noqa: TRY004
    if isinstance(publication_date, date):
        return publication_date.isoformat()
    stated = _stated(publication_date)
    try:
        return date.fromisoformat(stated).isoformat()
    except ValueError as error:
        raise ValueError(f"publication_date does not state a day: {publication_date!r}") from error


#: The X family's own spelling, split right-anchored: a two-digit year, then a
#: sequence of any width, then the month and day as the LAST FOUR digits. The
#: anchor is the point -- reading left-to-right with a fixed-width sequence is
#: exactly the mistake that hid 206 documents.
_FRDOC_X_SPELLING = re.compile(r"\AX(?P<yy>[0-9]{2})-(?P<seq>[0-9]+)(?P<mm>[0-9]{2})(?P<dd>[0-9]{2})\Z")


def _frdoc_x_states_its_day(text: str, publication_date: object) -> None:
    """Raise where an X number's OWN encoded day contradicts the caller's.

    The X form carries its publication date, and across the whole pinned
    column it carries it correctly: 4,400 of 4,400 agree. That is what makes a
    disagreement worth raising on rather than ignoring -- it is a DETECTABLE
    DEFECT, not the ambiguity the legacy form has, and the only two ways to
    reach one are a caller pairing the wrong date with the number or a corpus
    row where the publisher's own two statements diverge. Both are worth
    stopping for; neither should mint quietly.

    The date is never part of an X identity, so a caller that states nothing
    is asking a smaller question and gets an answer, not a complaint.
    """

    if publication_date is None:
        return
    match = _FRDOC_X_SPELLING.fullmatch(text)
    if match is None:  # not this family; nothing of its own to contradict
        return
    stated = _publication_day(publication_date)
    encoded = f"{match['mm']}-{match['dd']}"
    if stated[5:] != encoded or stated[2:4] != match["yy"]:
        raise ValueError(
            f"{text} encodes {match['yy']}-{encoded} and the caller states {stated}: "
            "an X number carries its own publication date, so a disagreement is a "
            "defect in one of them rather than a spelling to choose between"
        )


def mint_federal_register_document_iri(
    document_number: object,
    *,
    column_licensed: bool = False,
    publication_date: object = None,
) -> MintedIdentifier | None:
    """Mint an identifier for a Federal Register document number.

    Three outcomes, and which one a value gets is the news:

    - ``rkaf:us-frdoc`` when rulespec's space can spell it —
      ``[0-9]{4}-[0-9]{3,5}``, which is **480,566 of the 1,004,233** distinct
      values in the pinned column (47.9%);
    - ``rkaf:us-frdoc-legacy`` when the value is a pre-2010 bare-legacy number
      AND the caller states its ``publication_date``. This space is
      DATE-QUALIFIED by construction, and that is rulespec's design rather
      than a convenience: the bare number does not identify a document, since
      "00-111" names two of them, and the corpus reported zero collisions only
      because it had already dropped one. So the date is part of the identity,
      not metadata beside it — which is why this outcome is unreachable
      without one, and why the same value with no date still takes the hatch
      below rather than minting a half-qualified identity. **394,128** values
      (39.2% of the column) can reach it. New with rulespec 0.2.0rc17; see
      REF-064;
    - ``rkaf:us-frdoc-x`` when the value is an X-family number, with or without
      a date, because that form carries its own: read right-anchored the last
      four digits are the month and day, and they agree with the publication
      date on **4,400 of 4,400** corpus rows. Stating a date is therefore
      optional and stating a WRONG one raises, which is a property the legacy
      space cannot have. New with rulespec 0.2.0rc18; see REF-065;
    - ``rkaf:partner-defined`` when the shape layer recognises the value and
      rulespec cannot spell it. It is reached through the prose reader by the
      correction and republication forms, by a legacy number nobody dated, and
      — behind ``column_licensed`` — by the letter-opening families that still
      have no space (E, C, R and Z:
      :data:`~identifier_shapes._FR_COLUMN_LETTER_FORMS`). Three populations
      have LEFT the hatch: the 28,862 modern-form numbers with a three- or
      four-digit tail (2010-5997, 2011-237, 2012-00019 among them) when rc16
      widened ``rkaf:us-frdoc``, the bare-legacy numbers when rc17 gave them a
      space, and the 4,400 X numbers when rc18 did;
    - ``None`` otherwise, which is a refusal and never a repair — including
      for the **five** modern-form numbers a hand-validated collision census
      names as naming two genuinely different documents (REF-066): checked
      FIRST, before any shape is even asked, because minting anything for
      one of these — even the partner hatch — would still be one identifier
      standing for two documents.

    **Five modern-form numbers refuse absolutely, and two mint exactly as
    normal, because they name different things (REF-066).** A 2026-09-02
    full crawl of the published Federal Register found seven modern-form
    document numbers that each carry two different publication dates —
    something the modern space, unlike the legacy space above, was never
    built to expect. Reading the actual documents (RefSpec
    ``research/evidence/fr-collision-census-2026-09-02/``) separated five
    genuine collisions (different agencies, different subjects — an EPA
    notice sharing ``2010-31094`` with an unrelated DOT/FAA rulemaking eleven
    months later, among them) from two that are one matter published twice,
    each explicitly a correction of its own document number ("In notice
    document 2015-17759 … make the following correction"). The five are
    refused outright by :func:`is_a_refused_federal_register_collision`,
    consulted before any other check: one lookup in
    :data:`_FR_COLLISION_VERDICTS`, whose evidence and witnesses stay in
    RefSpec. Minting an ordinary number therefore reaches no census file, no
    witness and no git — it is a pure function of the value in every
    deployment, which an audit on 2026-09-02 found it briefly was not
    (REF-066). The two mint ``rkaf:us-frdoc`` exactly as any
    other modern number would, because one identifier for one matter
    published twice is correct, not merely tolerated.

    ``column_licensed`` is the whole of the two-readers doctrine in this
    module, delegated whole to
    :func:`~identifier_shapes.is_federal_register_document_number`'s own
    ``column_licensed`` flag — this function adds no second opinion about
    what the column licenses. Unlabeled in running text "94-12345" is
    indistinguishable from a docket or a release number and stays unread;
    arriving from a ``document_number`` field it needs no inference, because
    the field is the license. Nothing about prose detection changes either
    way — the flag admits shapes and admits them nowhere else. See
    :data:`~identifier_shapes.BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`
    and :data:`~identifier_shapes._FR_COLUMN_LETTER_FORMS`.

    **The year prefix is never checked against the date, and that refusal is
    measured.** A legacy number's leading two digits usually restate its
    publication year, and a fence on the disagreement is the obvious next
    thought — but 1,661 of the 395,498 bare-legacy values (0.42%) genuinely
    disagree, systematic year-boundary spillover where a number issued in late
    December is published in early January (07-6308 on 2008-01-15, 94-* into
    1995, 01-* into 2002). The sibling letter families do the same thing at
    larger scale (E8 spills 318 documents into 2009). So the prefix is a
    spelling, the date is the caller's fact, and this function refuses to
    adjudicate between them: adding that check would silently refuse 1,661
    real documents.

    The padding is never normalized, and after the widening that rule is the
    only thing standing between a document and a second identifier. The Office
    of the Federal Register pads some years and not others; across all 480,566
    modern-form values now inside the space, not one padded number has an
    unpadded twin — measured, and the load-bearing safety proof for widening
    the space at all. So 2012-00019 is the identifier and "2012-19" would be a
    spelling no publisher issued.
    """

    text = _stated(document_number).translate(_DASHES)
    if is_a_refused_federal_register_collision(text):
        return None
    if not (
        is_federal_register_document_number(text, column_licensed=column_licensed)
        or _states_a_federal_register_document(text)
    ):
        return None
    minted = _mint("rkaf:us-frdoc", f"urn:rkaf:us:frdoc:{text}")
    if minted is not None:
        return minted
    _frdoc_x_states_its_day(text, publication_date)
    self_dating = _mint("rkaf:us-frdoc-x", f"urn:rkaf:us:frdoc-x:{text}")
    if self_dating is not None:
        return self_dating
    if publication_date is not None:
        dated = _mint(
            "rkaf:us-frdoc-legacy",
            f"urn:rkaf:us:frdoc-legacy:{text}:{_publication_day(publication_date)}",
        )
        if dated is not None:
            return dated
    return mint_partner_iri("frdoc", text)


def mint_partner_iri(kind: str, value: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:partner:refspec:{kind}:{value}`` under the escape hatch.

    rulespec's ``rkaf:partner-defined`` is how a real thing its own spaces
    cannot spell stays losslessly identifiable, and this is the only minter
    here that adds identity rather than restating rulespec's. So it folds
    nothing: no dash collapse, no case fold. Whatever a caller hands it comes
    back recoverable, because a value that reached this function did so
    precisely because no space would normalize it.

    The value is percent-encoded (RFC 3986 unreserved set kept), which is what
    makes the result satisfy rkaf's ``[^\\s]+`` identifier floor without
    dropping a character. Encode ONCE: handing this function an
    already-encoded value produces a different, wrong identifier, since "%"
    itself encodes.

    Refuses a C0 control character (below U+0020), which is damage rather
    than identity and percent-encoding would otherwise hide as "%0A"; DEL
    (U+007F) and the C1 controls (U+0080-U+009F) are not refused: inside the
    stripped value they are percent-encoded like any other character.
    Refuses an empty value;
    and refuses a ``kind`` outside ``[a-z][a-z0-9-]*`` so the five-segment
    layout always parses back unambiguously. Reusing a real family's word as
    the kind is deliberate, not a shadow: the FR minter itself hands the
    394,128 bare-legacy and 127,523 letter-opening documents here as kind
    ``frdoc``, and the ``urn:rkaf:partner:refspec:`` prefix is what keeps
    them lexically apart from every ``urn:rkaf:us:...`` identifier.

    The hatch is a WAITING ROOM, not a parallel vocabulary. When rulespec
    widens a space, whatever it now admits leaves through the same door it
    came in: ``urn:rkaf:partner:refspec:frdoc:2011-237`` became
    ``urn:rkaf:us:frdoc:2011-237`` in 0.2.0rc16 with no lookup, because the
    value is percent-encoded here losslessly and is recoverable from the
    partner IRI itself. See REF-054 for what that obliges a future widening
    to check.
    """

    text = _stated(value)
    # TODO: refuse DEL and C1 controls too, in RefSpec's mint_partner_iri and here in one change, so the two stay equal.
    if not text or _PARTNER_KIND.fullmatch(kind) is None or any(ord(character) < 32 for character in text):
        return None
    return _mint("rkaf:partner-defined", f"urn:rkaf:partner:{PARTNER_NAMESPACE}:{kind}:{quote(text, safe='')}")
