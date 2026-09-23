"""The minting layer, each rule pinned by the evidence that bought it.

Every specimen is a real identifier: Federal Register document numbers and
bare-legacy witnesses from RefSpec's pinned ``document_number`` column
(1,004,233 distinct, read 2026-08-31), RINs/dockets/CFR parts from
:mod:`identifier_shapes` and :mod:`citation_grammar`.

Ported with the module from RefSpec ``tests/test_iri_minting.py`` at RefSpec
``4a680c81``: every test that reads only strings is here unchanged apart from
the import path. Six stay in RefSpec. Two hold the lexical spaces true against
the vendored ``rulespec-conformance`` wheel, which this repository does not
depend on; three sweep RefSpec's pinned Federal Register and Agenda columns;
and one proves an ordinary mint never reaches RefSpec's hand-validated
evidence, which this module does not import at all. The structural test below
also dropped RefSpec's ``canonical_usc_iri`` from its floor sweep, because
that minter stays in RefSpec. Nothing here holds the moved collision table or
the lexical spaces to their sources, which spicy-docs cannot import; RefSpec
does once it adopts the module (``docs/decisions.md``).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest

from spicy_docs.interpretation import identifier_shapes
from spicy_docs.interpretation.citation_grammar import (
    CFR_LETTERED_PART_SHARE,
    CFR_TITLE_COUNT,
    CONGRESS_CURRENT,
    EO_HIGHEST_KNOWN,
    parse_cfr_citations,
)
from spicy_docs.interpretation.iri_minting import (
    BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER,
    IDENTIFIER_SPACES,
    PARTNER_NAMESPACE,
    MintedIdentifier,
    mint_cfr_iri,
    mint_executive_order_iri,
    mint_federal_register_document_iri,
    mint_partner_iri,
    mint_public_law_iri,
    mint_regulations_gov_docket_iri,
    mint_rin_iri,
)

#: One real, minting call per family, so a property test sweeps the whole
#: surface rather than one minter's habits. Each specimen is cited at the test
#: that states its rule.
EVERY_FAMILY: tuple[tuple[str, MintedIdentifier | None], ...] = (
    ("cfr", mint_cfr_iri(7, "273", "9")),
    ("cfr-part-only", mint_cfr_iri(40, "60")),
    ("cfr-lettered-part", mint_cfr_iri(7, "15a")),
    ("eo", mint_executive_order_iri(12_866)),
    ("rin", mint_rin_iri("2060-AV16")),
    ("regsgov", mint_regulations_gov_docket_iri("EPA-HQ-OAR-2021-0317")),
    ("pl", mint_public_law_iri("119-101")),
    ("frdoc", mint_federal_register_document_iri("2024-00366")),
    # 2011-237 was the "frdoc-partner" specimen until rulespec 0.2.0rc16
    # widened the space; it is first-class now, which is the whole delivery of
    # that widening. The partner specimen moved to a letter-opening value,
    # which is a population the hatch still holds (127,523 of them; 117,292
    # is the PROSE reader's share of it, not the hatch's).
    ("frdoc-short-tail", mint_federal_register_document_iri("2011-237")),
    ("frdoc-partner", mint_federal_register_document_iri("E8-24348")),
    ("frdoc-bare-legacy", mint_federal_register_document_iri("09-19806", column_licensed=True)),
    ("partner", mint_partner_iri("proceeding", "EPA-HQ-OAR-2021-0317")),
)


# --------------------------------------------------------------------------- #
# The structural guarantee.


def test_no_minter_emits_an_identifier_the_contract_would_reject() -> None:
    """Pin every family against its declared space and rkaf's generic identifier floor, the same floor RefSpec checks
    canonical_usc_iri against.
    """

    floor = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
    minted = [identifier for _, identifier in EVERY_FAMILY]
    assert all(identifier is not None for identifier in minted)
    for name, identifier in EVERY_FAMILY:
        assert identifier is not None, name
        assert IDENTIFIER_SPACES[identifier.scheme].fullmatch(identifier.iri), name
        assert floor.fullmatch(identifier.iri), name

    for iri in (i.iri for i in minted if i):
        assert floor.fullmatch(iri), iri
        assert iri.startswith("urn:rkaf:"), iri
        assert iri == iri.strip() and iri.isascii(), iri
        assert "" not in iri.split(":"), iri


def test_the_type_refuses_to_hold_an_identifier_outside_its_space() -> None:
    """Pin that MintedIdentifier raises for an undeclared scheme and for an IRI outside its scheme's space.

    The minters refuse with ``None``; the raise exists for a consumer
    assembling the pair by hand, the only way an unchecked identifier could
    reach rkaf.
    """

    # The scheme below is one substitution from a real one and deliberately
    # undeclared; it is spelled in two halves because writing it whole would
    # claim a term the rkaf term-currency sweep must keep refusing.
    with pytest.raises(ValueError, match="undeclared identifier scheme"):
        MintedIdentifier(scheme="rkaf:" + "us-uscode", iri="urn:rkaf:us:usc:42:7411")
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-eo", iri="urn:rkaf:us:eo:012866")
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-frdoc", iri="urn:rkaf:us:frdoc:09-19806")
    # And the pair a well-formed IRI under the wrong scheme would make.
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-pl", iri="urn:rkaf:us:eo:12866")


def test_minting_is_a_function_of_the_identifier_and_nothing_else() -> None:
    """Pin that equivalent spellings converge to one identifier across RIN case, docket labels, zero-padded CFR titles,
    and unicode dashes.
    """

    assert mint_cfr_iri(7, "273", "9") == mint_cfr_iri(7, "273", "9")
    assert mint_federal_register_document_iri("09-19806", column_licensed=True) == mint_federal_register_document_iri(
        "09-19806", column_licensed=True
    )

    assert mint_rin_iri("2060-av16") == mint_rin_iri("2060-AV16")
    assert mint_rin_iri("2060–AV16") == mint_rin_iri("2060-AV16")
    assert mint_regulations_gov_docket_iri("Docket No. FDA-2011-N-0002") == mint_regulations_gov_docket_iri(
        "fda-2011-n-0002"
    )
    assert mint_cfr_iri("07", "1943") == mint_cfr_iri(7, 1943)
    assert mint_public_law_iri("119–101") == mint_public_law_iri("119-101")
    assert mint_executive_order_iri("012866") == mint_executive_order_iri(12_866)
    assert mint_federal_register_document_iri("2024-00366") == mint_federal_register_document_iri(" 2024-00366 ")


# --------------------------------------------------------------------------- #
# CFR.


def test_a_cfr_citation_mints_title_part_and_section() -> None:
    """Pin title/part/section minting (7 CFR 273.9, 49 CFR 1.95) and the part-only form."""

    assert mint_cfr_iri(7, "273", "9").iri == "urn:rkaf:us:cfr:7:273.9"
    assert mint_cfr_iri(49, "1", "95").iri == "urn:rkaf:us:cfr:49:1.95"
    assert mint_cfr_iri(40, "60").iri == "urn:rkaf:us:cfr:40:60"
    assert mint_cfr_iri(7, "273", "9").scheme == "rkaf:us-cfr"


def test_a_cfr_subsection_resolves_to_its_section() -> None:
    """Pin that a subsection parenthetical is dropped to its section rather than refusing the whole citation."""

    assert mint_cfr_iri(40, "60", "18(a)") == mint_cfr_iri(40, "60", "18")


def test_a_lettered_cfr_part_mints_and_its_case_is_folded() -> None:
    """Pin that lettered parts (7 CFR 15a) stay distinct from their numeric sibling, with the uppercase fold lossless.

    83 of the OFR's 272 non-numeric parts carry a single letter; every ancestor
    of the grammar merged "15" and "15a", and the fold is the only path that
    makes the publisher's uppercase spellings (26 CFR 16A and three others)
    mintable without truncating them.
    """

    lettered, total = CFR_LETTERED_PART_SHARE
    assert 0 < lettered < total  # the population the widening reaches

    assert parse_cfr_citations("7 CFR 15a")[0].cfr_part == "15a"
    assert mint_cfr_iri(7, "15a").iri == "urn:rkaf:us:cfr:7:15a"
    assert mint_cfr_iri(7, "15").iri == "urn:rkaf:us:cfr:7:15"
    assert mint_cfr_iri(7, "15a") != mint_cfr_iri(7, "15")

    # The uppercase fold, on the only path that produces uppercase.
    assert parse_cfr_citations("26 CFR 16A")[0].cfr_part == "16A"
    assert mint_cfr_iri(26, "16A").iri == "urn:rkaf:us:cfr:26:16a"
    assert mint_cfr_iri(26, "16A") == mint_cfr_iri(26, "16a")
    assert mint_cfr_iri(26, "16").iri == "urn:rkaf:us:cfr:26:16"  # folding, never truncating

    # Still refused: no multi-letter part suffix exists anywhere in the index.
    assert mint_cfr_iri(7, "15ab") is None


def test_a_hyphen_numbered_cfr_part_is_in_the_space_and_out_of_the_minter() -> None:
    """Pin that the space accepts a hyphen-numbered part while the minter refuses it.

    REF-054 recorded the deferred phantom -- "41 CFR 101-1" reading as part
    101 -- and named the reopen trigger: a receipt-authorized
    ``citation_grammar`` rebuild capturing the complete hyphenated part. That
    rebuild is 61bb05d0 (range preservation), so the reader now keeps
    ``101-1`` and the phantom is unreachable. The minter still refuses the
    hyphen branch: no pinned column carries a hyphen part, and title 41's
    hyphen heads are not parts in their own right.
    """

    # The contract accepts it: the space is rulespec's, and it is right.
    assert IDENTIFIER_SPACES["rkaf:us-cfr"].fullmatch("urn:rkaf:us:cfr:41:101-1")
    # The minter does not.
    assert mint_cfr_iri(41, "101-1") is None
    assert mint_cfr_iri(41, "101-1", "20") is None

    # The phantom is closed: the reader keeps the whole hyphenated token, and
    # a numeric part handed to the minter directly is still a legal part.
    assert parse_cfr_citations("41 CFR 101-1")[0].cfr_part == "101-1"
    assert mint_cfr_iri(41, "101").iri == "urn:rkaf:us:cfr:41:101"


def test_an_impossible_cfr_title_mints_nothing() -> None:
    """Pin that the grammar keeps an impossible title for inspection while the minter refuses it, reserving only title
    35.
    """

    assert mint_cfr_iri(CFR_TITLE_COUNT, "1") is not None
    assert mint_cfr_iri(CFR_TITLE_COUNT + 1, "1") is None
    assert mint_cfr_iri(35, "1") is not None  # Reserved today; the Panama Canal until 2000
    assert mint_cfr_iri(0, "1") is None
    assert mint_cfr_iri(16, "0").iri == "urn:rkaf:us:cfr:16:0"  # Published Organization part.


def test_a_section_that_states_nothing_is_no_section_rather_than_a_bad_one() -> None:
    """Pin that blank-section sentinels from ``states_nothing`` fall back to the part while a stated unspellable section
    refuses the citation.
    """

    for blank in (None, "", "  ", "None", "N/A", "Not Yet Determined"):
        assert mint_cfr_iri(40, "60", blank) == mint_cfr_iri(40, "60"), blank
    for unspellable in ("60 to 65", "Appendix A", "18.5"):
        assert mint_cfr_iri(40, "60", unspellable) is None, unspellable


def test_the_part_canonicalization_agrees_with_the_grammar() -> None:
    """Pin that minting from raw components and from a parsed citation land on one identifier for padded and subsection
    forms.
    """

    for text, components in (
        ("40 CFR 0060", ("40", "0060", None)),
        ("07 CFR 1943", ("07", "1943", None)),
        ("40 CFR 60.18(a)", ("40", "60", "18(a)")),
        ("49 CFR 1.95", ("49", "1", "95")),
    ):
        (citation,) = parse_cfr_citations(text)
        from_grammar = mint_cfr_iri(citation.cfr_title, citation.cfr_part, citation.cfr_section)
        assert from_grammar == mint_cfr_iri(*components), text
        assert from_grammar is not None, text


# --------------------------------------------------------------------------- #
# Executive orders.


def test_an_executive_order_mints_from_its_number() -> None:
    """Pin EO minting from the number (12866, 13990, 14008)."""

    assert mint_executive_order_iri(12_866).iri == "urn:rkaf:us:eo:12866"
    assert mint_executive_order_iri("13990").iri == "urn:rkaf:us:eo:13990"
    assert mint_executive_order_iri(14_008).scheme == "rkaf:us-eo"


def test_an_order_beyond_the_dated_bound_still_mints() -> None:
    """Pin that EO_HIGHEST_KNOWN is a dated capture bound, not a minting fence: the next order still mints."""

    assert mint_executive_order_iri(EO_HIGHEST_KNOWN) is not None
    assert mint_executive_order_iri(EO_HIGHEST_KNOWN + 1_000) is not None


def test_what_is_not_an_order_number_mints_nothing() -> None:
    """Pin that the series starts at 1: zero, empty, malformed, and page-locator forms mint nothing."""

    for stated in (0, "0", "", None, "12866.0", "EO 12866", "12,866", "٣"):
        assert mint_executive_order_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# RINs.


def test_a_rin_mints_and_a_sentinel_does_not() -> None:
    """Pin RIN minting and refusal of the literal "Not Assigned" sentinel (56,364 of 64,537 catalog values).

    The minter wraps a validator that answers "is this string one", never "does
    it contain one"; admitted by containment the sentinel became the corpus's
    most common identifier tenfold.
    """

    assert mint_rin_iri("2060-AV16").iri == "urn:rkaf:us:rin:2060-AV16"
    assert mint_rin_iri("0301-AA00").iri == "urn:rkaf:us:rin:0301-AA00"
    assert mint_rin_iri("2060-AV16 ").iri == "urn:rkaf:us:rin:2060-AV16"  # surrounding space is not identity
    for stated in ("Not Assigned", "", None, "RIN 2060-AV16", "3235-0695", "2060-AV1"):
        assert mint_rin_iri(stated) is None, stated


def test_a_rin_the_shape_admits_and_rkaf_cannot_spell_is_refused() -> None:
    """Pin the syntax distinction: the shape admits ``[A-Za-z0-9]{2}`` but rkaf's space closes on ``[0-9]{2}``."""

    assert identifier_shapes.is_regulation_identifier_number("0648-ABCD")
    assert mint_rin_iri("0648-ABCD") is None


def test_a_real_rin_outside_the_shape_is_refused_not_repaired() -> None:
    """Pin that five real-but-out-of-shape RINs are refused rather than repaired; refusal contradicts no historical
    publisher attestation.
    """

    for real_but_unminted in ("0648-XD990", "0648-XC705", "3090-00XX", "1115-09AE", "2070-78AB"):
        assert mint_rin_iri(real_but_unminted) is None, real_but_unminted


# --------------------------------------------------------------------------- #
# Regulations.gov dockets.


def test_a_docket_mints_through_the_label_and_not_around_it() -> None:
    """Pin strip-then-validate: labels are stripped (DOC-2010-0001 survives), a digit-opening remainder is not an
    identifier, and a FERC-shaped docket refuses.
    """

    assert mint_regulations_gov_docket_iri("EPA-HQ-OAR-2021-0317").iri == "urn:rkaf:us:regsgov:EPA-HQ-OAR-2021-0317"
    assert mint_regulations_gov_docket_iri("Docket No. FDA-2011-N-0002").iri == "urn:rkaf:us:regsgov:FDA-2011-N-0002"
    assert mint_regulations_gov_docket_iri("DHS Docket No. USCIS-2025-0004") is not None
    assert mint_regulations_gov_docket_iri("DOC-2010-0001").iri == "urn:rkaf:us:regsgov:DOC-2010-0001"
    assert mint_regulations_gov_docket_iri("ACF_FRDOC_0001").iri == "urn:rkaf:us:regsgov:ACF_FRDOC_0001"

    assert mint_regulations_gov_docket_iri("MM Docket No. 98-213") is None
    assert mint_regulations_gov_docket_iri("CP26-20-000") is None
    for states_nothing in ("Docket No.", "", None, "None", "nan", "null"):
        assert mint_regulations_gov_docket_iri(states_nothing) is None, states_nothing


def test_the_docket_minter_inherits_the_column_readers_license() -> None:
    """Pin that the docket minter is exactly as wide as the column reader it wraps, so a document id must not be handed
    to it.

    The column reader absorbs "EPA-HQ-OAR-2021-0317-0001" whole; the prose
    reader arbitrates the same characters as a document, and that arbitration
    belongs upstream.
    """

    assert IDENTIFIER_SPACES["rkaf:us-regsgov"].fullmatch("urn:rkaf:us:regsgov:EPA-HQ-OAR-2021-0317-0001")

    document = "EPA-HQ-OAR-2021-0317-0001"
    assert identifier_shapes.normalize_docket_reference(document) == document
    assert mint_regulations_gov_docket_iri(document).iri == f"urn:rkaf:us:regsgov:{document}"

    (prose,) = identifier_shapes.detect_identifier_shapes(document)
    assert prose.kind is identifier_shapes.IdentifierKind.REGULATIONS_GOV_DOCUMENT
    (docket,) = identifier_shapes.detect_identifier_shapes("EPA-HQ-OAR-2021-0317")
    assert docket.kind is identifier_shapes.IdentifierKind.DOCKET


# --------------------------------------------------------------------------- #
# Public laws.


def test_a_public_law_mints_from_the_compound_the_grammar_produces() -> None:
    """Pin Public Law minting from the compound the grammar produces (119-101, 116-260)."""

    assert mint_public_law_iri("119-101").iri == "urn:rkaf:us:pl:119-101"
    assert mint_public_law_iri("116-260").iri == "urn:rkaf:us:pl:116-260"
    assert mint_public_law_iri("119-101").scheme == "rkaf:us-pl"


def test_a_law_of_a_congress_that_has_not_sat_still_mints() -> None:
    """Pin that CONGRESS_CURRENT is a dated fact, not a minting fence: the next Congress's first law mints."""

    assert mint_public_law_iri(f"{CONGRESS_CURRENT + 1}-1") is not None


def test_what_is_not_a_public_law_number_mints_nothing() -> None:
    """Pin that a session-law chapter ("1955:360") and malformed forms mint nothing."""

    for stated in ("1955:360", "Pub. L. 119-101", "119", "119-", "0-1", "119-0", "", None):
        assert mint_public_law_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# Federal Register documents: the three outcomes.


def test_a_modern_document_number_rkaf_can_spell_mints_first_class() -> None:
    """Pin modern-form document numbers as first-class rkaf:us-frdoc identifiers (480,566 of 1,004,233 distinct values)."""

    for value in ("2024-00366", "2026-13078", "2012-00019"):
        minted = mint_federal_register_document_iri(value)
        assert minted == MintedIdentifier(scheme="rkaf:us-frdoc", iri=f"urn:rkaf:us:frdoc:{value}"), value


def test_a_short_tail_is_real_and_is_now_first_class() -> None:
    """Pin that three- and four-digit tails are first-class since rc16 widened the space to ``[0-9]{4}-[0-9]{3,5}``.

    The widening splits no identity: across all 480,566 admitted values no
    document has both a padded and an unpadded spelling, so no value gained a
    second first-class identifier.
    """

    assert IDENTIFIER_SPACES["rkaf:us-frdoc"].fullmatch("urn:rkaf:us:frdoc:2011-237")
    for value in ("2010-5997", "2011-237", "2012-999", "2013-1234"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:us-frdoc", value
        assert minted.iri == f"urn:rkaf:us:frdoc:{value}", value


def test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it() -> None:
    """Pin the three-digit floor as co-extensive with ``identifier_shapes``: below it values mint only through the
    partner hatch, and six-digit tails refuse.

    The floor cuts a continuous series and is held for consistency with the
    layer that reads it, not because evidence puts a boundary there; the
    ceiling is measured (zero six-digit tails, largest sequence ever 33,861).
    """

    for below in ("2010-99", "2024-36", "2011-7"):
        assert mint_federal_register_document_iri(below) is None, below
        licensed = mint_federal_register_document_iri(below, column_licensed=True)
        assert licensed is not None, below
        assert licensed.scheme == "rkaf:partner-defined", below
    for above in ("2024-003661", "2010-1234567"):
        assert mint_federal_register_document_iri(above) is None, above

    assert mint_federal_register_document_iri("2010-100").iri == "urn:rkaf:us:frdoc:2010-100"


def test_the_letter_opening_forms_keep_the_identity_the_shape_layer_reads() -> None:
    """Pin that E/C/R letter-opening forms mint through the partner hatch using only shapes the shape layer already
    reads whole.
    """

    for value in ("E7-21559", "C1-2026-13078", "R1-2010-13257", "R1-10679"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:partner-defined", value

    for real_but_unread in ("Z9-802", "E9-23", "X10-11220", "E3-2013-2261"):
        assert mint_federal_register_document_iri(real_but_unread) is None, real_but_unread
    assert mint_federal_register_document_iri("FR Doc. 2026-13078") is None


def test_the_four_letter_opening_families_need_the_column_license_too() -> None:
    """Pin REF-052/REF-054's four letter-opening families at the mint layer: unlicensed they are unread, licensed E/Z/E3
    still use the hatch while X moved to its own rkaf:us-frdoc-x space in rc18 (REF-065).
    """

    for value in ("E9-654", "Z9-9", "E3-2013-2261"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # X still needs the license -- a date-free letter form is no more readable
    # in prose than a bare legacy number -- but it now lands in its own space.
    for value in ("X10-11220", "X09-101207"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None and licensed.scheme == "rkaf:us-frdoc-x", value

    # The 99 short-tail corrections and the fused-colophon values REF-054
    # keeps refused stay refused, licensed or not -- the four families do not
    # reach for a second unmeasured population.
    for still_refused in ("C1-2012-19", "C1-2012-2091"):
        assert mint_federal_register_document_iri(still_refused, column_licensed=True) is None, still_refused


def test_the_bare_legacy_form_needs_the_column_license_and_only_that() -> None:
    """Pin §1.2: a bare legacy number is unread in prose and mints only under ``column_licensed``, through the partner
    hatch.
    """

    assert identifier_shapes.detect_identifier_shapes("09-19806") == []
    assert not identifier_shapes.is_federal_register_document_number("09-19806")

    assert mint_federal_register_document_iri("09-19806") is None
    minted = mint_federal_register_document_iri("09-19806", column_licensed=True)
    assert minted == MintedIdentifier(
        scheme="rkaf:partner-defined", iri=f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:09-19806"
    )

    # The whole era, not one witness: the first and last bare-legacy documents
    # in the pinned column are 1994-01-03 and 2009-08-19. (REF-056 widens a
    # further, disjoint production for the one- and two-digit tail this
    # constant's own docstring names and defers -- see
    # test_the_bare_legacy_short_tail_family_needs_the_column_license_too --
    # so the equivalence below stays exactly this constant's own shape.)
    for value in ("94-120124", "95-170007", "97-339151", "08-1234"):
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert (licensed is not None) == (re.fullmatch(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER, value) is not None)
        assert mint_federal_register_document_iri(value) is None, value


def test_the_bare_legacy_shape_stops_where_the_measurement_stops() -> None:
    """Pin the bare-legacy tail at three to six digits: short tails go through REF-056's sibling production, seven-plus
    refuse, and four named unadmitted column values stay refused.
    """

    shape = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)
    assert shape.fullmatch("09-19806") and shape.fullmatch("94-120124")
    assert not shape.fullmatch("00-10") and not shape.fullmatch("00-1")
    assert not shape.fullmatch("94-1234567")
    # Refused by THIS shape, but not by the mint layer any more -- REF-056's
    # sibling production reads it; see
    # test_the_bare_legacy_short_tail_family_needs_the_column_license_too.
    assert mint_federal_register_document_iri("00-10", column_licensed=True) is not None
    assert mint_federal_register_document_iri("94-1234567", column_licensed=True) is None
    # Four values the column really carries and no production admits. They
    # are NOT all damage, and the difference is worth stating rather than
    # flattening: "94-22818Filed" and "00-2999Doc" are the colophon fusion
    # the module's research notes attest (the printed page welded the next
    # word on); "95-95-744" is the publisher's own number, printed
    # "[FR Doc. 95-95-744 Filed 1-11-95; 8:45 am]" on 60 FR 2992, with an
    # extra hyphenated segment no shape reads; and "94-S16142" is a spelling
    # whose document the publisher numbers "94-00000" instead. Refusal is
    # what they share; damage is not. See the partition in
    # `test_the_document_number_column_is_accounted_for_exactly`.
    for refused in ("94-22818Filed", "94-S16142", "00-2999Doc", "95-95-744"):
        assert mint_federal_register_document_iri(refused, column_licensed=True) is None, refused


def test_the_bare_legacy_short_tail_family_needs_the_column_license_too() -> None:
    """Pin REF-056's one- and two-digit bare-legacy tails (1,370 values) as column-licensed-only partner-hatch mints,
    with the six-digit ceiling untouched.
    """

    for value in ("00-1", "00-10", "93-54"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # The ceiling REF-052 already measured (six digits) is untouched --
    # only the floor moved.
    assert mint_federal_register_document_iri("94-1234567", column_licensed=True) is None


def test_the_modern_short_tail_family_needs_the_column_license_too() -> None:
    """Pin REF-056's one- and two-digit modern tails (286 values) as column-licensed-only partner-hatch mints, leaving
    rulespec's own space untouched.
    """

    for value in ("2010-1", "2010-10", "2013-58"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # Three digits and up is rulespec's own space, unmoved by this ruling.
    assert mint_federal_register_document_iri("2010-100").iri == "urn:rkaf:us:frdoc:2010-100"


def test_document_number_padding_is_never_normalized_away() -> None:
    """Pin that padding is identity: padded and unpadded spellings stay different identifiers, including the three real
    near-collision pairs.

    The pad is preserved because it is the spelling the publisher issued;
    nothing is folded away, and the letter of a letter-opening value is kept
    for the same reason.
    """

    padded = mint_federal_register_document_iri("2012-00019")
    unpadded = mint_federal_register_document_iri("2012-19")
    assert padded is not None and padded.iri == "urn:rkaf:us:frdoc:2012-00019"
    assert unpadded is None  # a two-digit tail states nothing the shape reads
    # Three digits and up, the pad is preserved rather than stripped: both of
    # these are inside the widened space, and they are not the same identifier.
    assert mint_federal_register_document_iri("2012-019").iri == "urn:rkaf:us:frdoc:2012-019"
    assert mint_federal_register_document_iri("2012-019") != mint_federal_register_document_iri("2012-19")

    # REF-056 is the floor lowering this docstring anticipated -- but only
    # for the column license, not for rulespec's own space: "2012-19" now
    # mints under ``column_licensed=True``, through the partner hatch, with
    # the literal two-digit spelling the value stated. It is still not the
    # same identifier as "2012-019": different scheme, different URN.
    licensed_unpadded = mint_federal_register_document_iri("2012-19", column_licensed=True)
    assert licensed_unpadded is not None
    assert licensed_unpadded.scheme == "rkaf:partner-defined"
    assert licensed_unpadded.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:2012-19"
    assert licensed_unpadded != mint_federal_register_document_iri("2012-019")

    # "2012-19"/"2012-019" is a HYPOTHETICAL pair: the column carries the
    # padded value and not the unpadded one, so it states the rule without
    # exercising it. REF-056 admitted 1,656 short-tail values, and three of
    # them turn the question real -- these are the only bare-short values in
    # the pinned column whose zero-padded twin is also there, found by
    # padding all 1,370 of them to every width from two digits to six and
    # looking each candidate up:
    for short, padded in (("96-30", "96-00030"), ("97-29", "97-00029"), ("97-63", "97-00063")):
        minted_short = mint_federal_register_document_iri(short, column_licensed=True)
        minted_padded = mint_federal_register_document_iri(padded, column_licensed=True)
        assert minted_short is not None and minted_padded is not None
        assert minted_short != minted_padded, (short, padded)
        assert minted_short.iri.endswith(f":frdoc:{short}"), short
        assert minted_padded.iri.endswith(f":frdoc:{padded}"), padded

    # The larger near-collision the widening opened is not padding at all: a
    # bare short tail and a letter-opening short tail can share their second
    # digit and their whole tail. 967 such pairs exist in the pinned column;
    # "00-1"/"C0-1" is the first alphabetically. The letter is a character
    # the value states, so the two stay distinct for the same reason the
    # padding does -- nothing is folded away.
    bare_short = mint_federal_register_document_iri("00-1", column_licensed=True)
    letter_short = mint_federal_register_document_iri("C0-1", column_licensed=True)
    assert bare_short is not None and letter_short is not None
    assert bare_short != letter_short
    assert bare_short.iri.endswith(":frdoc:00-1") and letter_short.iri.endswith(":frdoc:C0-1")


# --------------------------------------------------------------------------- #
# The partner-defined escape hatch.


def test_the_partner_hatch_is_lossless_and_fenced() -> None:
    """Pin the partner hatch's lossless percent-encoded layout, its kind and value fences, and that reusing a real
    family's word as the kind is deliberate, not a shadow.
    """

    minted = mint_partner_iri("proceeding", "EPA-HQ-OAR-2021-0317")
    assert minted == MintedIdentifier(
        scheme="rkaf:partner-defined",
        iri=f"urn:rkaf:partner:{PARTNER_NAMESPACE}:proceeding:EPA-HQ-OAR-2021-0317",
    )
    assert mint_partner_iri("frdoc", "Docket No. 7").iri.endswith("Docket%20No.%207")
    assert mint_partner_iri("frdoc", "E7-21559") != mint_partner_iri("frdoc", "e7-21559")

    # The kind fence keeps the five-segment layout parseable — no URN
    # machinery, no case variants — and damage is not identity.
    for kind in ("USC", "us:usc", "", "9frdoc", "frdoc/x"):
        assert mint_partner_iri(kind, "x") is None, kind
    for value in ("", None, "  ", "a\nb", "a\tb"):
        assert mint_partner_iri("frdoc", value) is None, value

    # Reusing a real family's word as the kind is DELIBERATE, not a shadow:
    # the FR minter itself mints kind "frdoc" beside rkaf:us-frdoc, and the
    # partner prefix is what keeps the namespaces apart. Pinned positively so
    # a future blocklist cannot land without noticing the module relies on it.
    #
    # The hatch is a waiting room, and rc16 emptied part of it: the 28,862
    # short-tail documents that used to be minted here as kind "frdoc" are
    # first-class now. That migration needed no lookup precisely because the
    # encoding below is lossless -- the partner IRI carries the source value,
    # so `partner:refspec:frdoc:2011-237` maps to `us:frdoc:2011-237` by
    # inspection. See REF-054.
    assert mint_partner_iri("usc", "note-only-citation").iri == (
        f"urn:rkaf:partner:{PARTNER_NAMESPACE}:usc:note-only-citation"
    )


# --------------------------------------------------------------------------- #
# The date-qualified legacy space (rulespec 0.2.0rc17, REF-064).


def test_a_dated_legacy_number_mints_the_qualified_space() -> None:
    """Pin rc17's qualified legacy space: with a publication date a bare number mints as
    ``urn:rkaf:us:frdoc-legacy:<value>:<day>``.
    """

    minted = mint_federal_register_document_iri("00-1", column_licensed=True, publication_date="2000-01-20")
    assert minted is not None
    assert minted.scheme == "rkaf:us-frdoc-legacy"
    assert minted.iri == "urn:rkaf:us:frdoc-legacy:00-1:2000-01-20"

    # A date object and the date32 a PyArrow column yields spell the same day.
    assert (
        mint_federal_register_document_iri("00-1", column_licensed=True, publication_date=date(2000, 1, 20)) == minted
    )

    # Every tail width rulespec's space admits, one to six digits.
    for value, day in (("09-19806", "2009-08-19"), ("94-10503", "1994-05-03")):
        one = mint_federal_register_document_iri(value, column_licensed=True, publication_date=day)
        assert one is not None and one.scheme == "rkaf:us-frdoc-legacy", value
        assert one.iri == f"urn:rkaf:us:frdoc-legacy:{value}:{day}", value


def test_the_same_legacy_number_on_two_days_is_two_identities() -> None:
    """Pin the negative fixture that justifies dating: "00-111" names two different documents, so undated it would merge
    them.
    """

    first = mint_federal_register_document_iri("00-111", column_licensed=True, publication_date="2000-01-03")
    second = mint_federal_register_document_iri("00-111", column_licensed=True, publication_date="2000-06-15")
    assert first is not None and second is not None
    assert first.iri != second.iri
    assert first.scheme == second.scheme == "rkaf:us-frdoc-legacy"


def test_an_undated_legacy_number_keeps_the_hatch_and_never_half_qualifies() -> None:
    """Pin that without a date a legacy number keeps the partner hatch rather than an identity whose date was guessed
    from the number.
    """

    undated = mint_federal_register_document_iri("09-19806", column_licensed=True)
    assert undated is not None
    assert undated.scheme == "rkaf:partner-defined"
    assert undated.iri == "urn:rkaf:partner:refspec:frdoc:09-19806"

    # The column license still governs: a date does not admit a value the
    # prose reader refuses, because the date is not a license.
    assert mint_federal_register_document_iri("09-19806", publication_date="2009-08-19") is None


def test_a_year_prefix_that_disagrees_with_its_date_still_mints() -> None:
    """Pin that the year prefix is a spelling, not a fence: 07-6308 published 2008-01-15 mints, one of 1,661
    year-boundary spills.
    """

    spilled = mint_federal_register_document_iri("07-6308", column_licensed=True, publication_date="2008-01-15")
    assert spilled is not None
    assert spilled.iri == "urn:rkaf:us:frdoc-legacy:07-6308:2008-01-15"


def test_a_publication_date_that_is_not_a_day_is_loud() -> None:
    """Pin that a non-day publication_date raises rather than downgrading to the hatch, while the compact ISO spelling
    mints the same identity.
    """

    for bad in ("not a date", "2009-13-45", "2009-08", "August 19, 2009", ""):
        with pytest.raises(ValueError, match="does not state a day"):
            mint_federal_register_document_iri("09-19806", column_licensed=True, publication_date=bad)

    # But a real day in ISO's compact spelling is a real day, and it mints the
    # SAME identity as the extended one. Deliberate, and the same doctrine as
    # the padding rule above: a spelling variant of one fact must not become a
    # second identifier.
    assert mint_federal_register_document_iri(
        "09-19806", column_licensed=True, publication_date="20090819"
    ) == mint_federal_register_document_iri("09-19806", column_licensed=True, publication_date="2009-08-19")

    with pytest.raises(ValueError, match="not an instant"):
        mint_federal_register_document_iri(
            "09-19806", column_licensed=True, publication_date=datetime(2009, 8, 19, 13, 45, tzinfo=UTC)
        )


def test_the_modern_space_is_untouched_by_a_date() -> None:
    """Pin that rkaf:us-frdoc answers first, so a date never qualifies a modern identity."""

    assert mint_federal_register_document_iri(
        "2024-00366", publication_date="2024-03-08"
    ) == mint_federal_register_document_iri("2024-00366")


# --------------------------------------------------------------------------- #
# The self-dating X space (rulespec 0.2.0rc18, REF-065).


def test_an_x_number_mints_without_a_date_because_it_carries_one() -> None:
    """Pin the self-dating X space: the number's last four digits are month and day, agreeing with publication_date on
    4,400 of 4,400 rows.
    """

    five = mint_federal_register_document_iri("X94-10503", column_licensed=True)
    assert five is not None
    assert five.scheme == "rkaf:us-frdoc-x"
    assert five.iri == "urn:rkaf:us:frdoc-x:X94-10503"

    # The six-digit tail a fixed-width space would have stranded: 206 real
    # documents, of which this is one (74 FR 64213, 2009-12-07, the DHS
    # Statement of Regulatory Priorities). Sequence 10, not sequence 1.
    six = mint_federal_register_document_iri("X09-101207", column_licensed=True)
    assert six is not None and six.scheme == "rkaf:us-frdoc-x"
    assert six.iri == "urn:rkaf:us:frdoc-x:X09-101207"


def test_an_x_number_and_its_bare_twin_are_different_identities() -> None:
    """Pin that the X prefix is identity: 2,382 of 4,400 X numbers have a bare twin that is a different document."""

    x = mint_federal_register_document_iri("X94-10503", column_licensed=True)
    bare = mint_federal_register_document_iri("94-10503", column_licensed=True, publication_date="1994-05-03")
    assert x is not None and bare is not None
    assert x.iri != bare.iri
    assert x.scheme == "rkaf:us-frdoc-x"
    assert bare.scheme == "rkaf:us-frdoc-legacy"


def test_an_x_number_whose_own_day_contradicts_the_caller_is_loud() -> None:
    """Pin the self-dating property as load-bearing: a stated date that contradicts the number raises rather than
    minting quietly.
    """

    assert mint_federal_register_document_iri(
        "X94-10503", column_licensed=True, publication_date="1994-05-03"
    ) == mint_federal_register_document_iri("X94-10503", column_licensed=True)

    for wrong in ("1994-05-04", "1994-06-03", "1995-05-03"):
        with pytest.raises(ValueError, match="carries its own publication date"):
            mint_federal_register_document_iri("X94-10503", column_licensed=True, publication_date=wrong)


def test_the_x_shape_layer_stops_where_the_corpus_does_and_the_space_does_not() -> None:
    """Pin the deliberate seven-digit-tail gap: rulespec's space is bounded by capacity, this shape layer by
    measurement, so a seven-digit X is spellable but not auto-detected.
    """

    assert mint_federal_register_document_iri("X26-9991231", column_licensed=True) is None
    assert mint_federal_register_document_iri("X09-101207", column_licensed=True) is not None


# --------------------------------------------------------------------------- #
# The modern-form collision refusal set (REF-066).


#: The seven modern-form document numbers a 2026-09-02 full crawl found
#: naming two documents each -- see
#: research/evidence/fr-collision-census-2026-09-02/README.md. Five are
#: genuinely different documents (refused); two are one matter published
#: twice (mint normally). Both halves are asserted below: a refusal test
#: alone would let a future reader "helpfully" refuse all seven.
_FR_COLLISION_REFUSALS = ("2010-31094", "2010-31384", "2010-31396", "2010-31415", "2010-517")
_FR_COLLISION_MINTS_NORMALLY = ("2015-17759", "2015-25354")


def test_the_five_collision_numbers_refuse_and_the_two_still_mint() -> None:
    """Pin REF-066's negative fixture: the five genuine collisions refuse, the two one-matter-published-twice values
    still mint.
    """

    for value in _FR_COLLISION_REFUSALS:
        assert mint_federal_register_document_iri(value) is None, value
        assert mint_federal_register_document_iri(value, column_licensed=True) is None, value

    for value in _FR_COLLISION_MINTS_NORMALLY:
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:us-frdoc"
        assert minted.iri == f"urn:rkaf:us:frdoc:{value}"


def test_a_refused_collision_number_never_falls_through_to_the_partner_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the refusal mechanism: a collision refuses before every branch, including the partner hatch, monkeypatched so
    it holds without the census.
    """

    from spicy_docs.interpretation import iri_minting as module

    fake_refused = "1994-99999"  # an otherwise-mintable modern-form number
    assert mint_federal_register_document_iri(fake_refused, column_licensed=True) is not None
    monkeypatch.setattr(module, "is_a_refused_federal_register_collision", lambda value: value == fake_refused)
    assert mint_federal_register_document_iri(fake_refused) is None
    assert mint_federal_register_document_iri(fake_refused, column_licensed=True) is None
    # An unrelated value is untouched by the monkeypatched predicate.
    assert mint_federal_register_document_iri("2024-00366") is not None
