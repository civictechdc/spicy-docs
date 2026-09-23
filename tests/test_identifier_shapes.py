"""Catalog identifier shapes, each rule pinned by the case that bought it.

Every specimen below was read out of one of two pinned columns before it was
written down here -- the Unified Agenda's ``rin`` column (46,547 distinct) and
the Federal Register corpus's ``document_number`` (1,004,233 distinct),
``docket_ids_json`` (608,758 distinct) and ``regulation_id_numbers_json``
(36,563 distinct), counted 2026-08-22. Tests state rules; the specimens are the
corpus's own witnesses to them, not invented inputs.

Ported with the module from RefSpec ``tests/test_identifier_shapes.py`` at
RefSpec ``4a680c81``, unchanged apart from the import path. The two tests that
read RefSpec's built Agenda and Federal Register artifacts stay in RefSpec
beside them. The tests for :func:`unpadded_federal_register_document_number`,
which is new here, are at the end.
"""

from __future__ import annotations

import itertools
import random
import re

import pytest

from spicy_docs.interpretation import identifier_shapes
from spicy_docs.interpretation.identifier_shapes import (
    BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER,
    FEDERAL_REGISTER_DOCUMENT_NUMBER,
    PUBLISHED_RIN,
    IdentifierCandidate,
    IdentifierKind,
    NumberingSystem,
    corrected_rin,
    detect_identifier_shapes,
    docket_reference_as_stated,
    is_federal_register_document_number,
    is_regulation_identifier_number,
    keep_longest_then_most_specific,
    normalize_docket_reference,
    normalize_docket_references,
    normalize_regsgov_identifier,
    normalize_rin,
    numbering_system,
    published_rin,
    unpadded_federal_register_document_number,
)

#: The dash spellings the module folds, restated here so the property tests
#: check the rule against an independent copy rather than against the
#: module's own table -- a test that imports the answer proves nothing.
DASH_FOLD = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))


def _kinds(text: str) -> list[tuple[str, str]]:
    """The (kind value, value) pairs the detector returns for a text."""
    return [(c.kind.value, c.value) for c in detect_identifier_shapes(text)]


def _dockets(text: str) -> list[str]:
    """The docket values the detector returns for a text."""
    return [c.value for c in detect_identifier_shapes(text) if c.kind is IdentifierKind.DOCKET]


#: Specimens copied verbatim out of the pinned columns, one per family the
#: corpus actually contains. Property tests sweep this list, so a property that
#: holds here holds on shapes the corpus really carries rather than on invented
#: ones.
CORPUS_SPECIMENS: tuple[str, ...] = (
    # Unified Agenda rin column
    "2060-AV45",
    "0301-AA00",
    "1018-BI73",
    # Federal Register regulation_id_numbers_json, damaged
    "1018-B173",
    "7100 AG79",
    "7100-AF 57",
    "3235-0695",
    "0648-X081",
    # Federal Register document_number
    "2026-13078",
    "2010-5997",
    "2011-237",
    "2012-00019",
    "E7-21559",
    "C1-2026-13078",
    "R1-2010-13257",
    "R1-10679",
    "Z9-802",
    "X10-11220",
    "94-12345",
    "2013-58",
    # Federal Register docket_ids_json
    "EPA-HQ-OAR-2021-0317",
    "EPA-HQ-OAR-2021-0317-0001",
    "FDA-2026-N-0008",
    "EERE-2022-BT-OT-0004",
    "Docket Nos. FDA-2025-E-0501 and FDA-2025-E-0502",
    "AMS-SC-25-0848",
    "CP26-20-000",
    "DOT_FRDOC_0001",
    "GIPSA-2008-FGIS-0002-NONRULEMAKING",
    "PPWOCRADN0-PCU00RP14.R50000",
    "Docket No. FSIS-2025-0012",
    "Docket Nos. FDA-2025-E-0162",
    "Docket ID: DoD-2026-OS-1552",
    "Docket No.: ED-2026-SCC-1519",
    "Docket #: EPA-R10-OAR-2014-0808",
    "Docket Number-NASA-2023-0005",
    "Docket. No. AMS-FTPP-20-0088",
    "DHS Docket No. USCIS-2025-0004",
    "Internal Agency Docket No. FEMA-1971-DR",
    "Airspace Docket No. 02-ACE-8",
    "MM Docket No. 98-213",
    "Notice 1",
    "File No. 500-1",
    "Rel. No. IC-24979",
    "OMB Control No. 2900-NEW",
    "Federal Register: December 28, 1994",
    "",
    "Not Assigned",
)


def _mutations(seed: int = 20260822, rounds: int = 40) -> list[str]:
    """Deterministic damage over the corpus specimens.

    Property tests need inputs the corpus does not contain but a reader could
    still be handed: a case flip, an en dash, stray padding, a truncation.
    Seeded so a failure is reproducible from the report alone.
    """

    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(rounds):
        text = rng.choice(CORPUS_SPECIMENS)
        operator = rng.randrange(6)
        if operator == 0:
            text = text.swapcase()
        elif operator == 1:
            text = text.replace("-", "–")
        elif operator == 2:
            text = f"  {text}  "
        elif operator == 3 and text:
            text = text[: rng.randrange(len(text))]
        elif operator == 4:
            text = f"see {text} in the record"
        else:
            text = text.replace("-", " ")
        out.append(text)
    return out


PROPERTY_CORPUS: tuple[str, ...] = tuple(CORPUS_SPECIMENS) + tuple(_mutations())


# --------------------------------------------------------------------------- #
# A validator answers "is", never "contains".


def test_a_validator_answers_is_not_contains() -> None:
    """56,364 of 64,537 catalog rin values are the literal "Not Assigned".

    Admitted by a containment test it became the corpus's most common
    identifier by a factor of ten.
    """

    assert is_regulation_identifier_number("2060-AV45")
    assert not is_regulation_identifier_number("Not Assigned")
    assert not is_regulation_identifier_number("RIN 2060-AV45")  # contains, is not
    assert normalize_rin("2060-av45") == "2060-AV45"
    assert normalize_rin("Not Assigned") is None
    # The same discipline on the other side of the join.
    assert is_federal_register_document_number("2026-13078")
    assert not is_federal_register_document_number("FR Doc. 2026-13078")
    assert normalize_docket_reference("EPA-HQ-OAR-2021-0317 and others") is None


@pytest.mark.parametrize("value", PROPERTY_CORPUS)
def test_a_predicate_and_its_normalizer_answer_the_same_question(value: str) -> None:
    """``is_x`` and ``normalize_x`` are one rule, so they cannot disagree.

    They did: the predicate required an exact ``str`` and read the value
    unstripped, while the normalizer stripped and coerced. " 2060-AV45" was a
    RIN to one and not to the other. No value in the four pinned columns
    carries surrounding whitespace, so unifying them costs nothing measured
    and removes a divergence that only ever produced a wrong answer.
    """

    assert is_regulation_identifier_number(value) == (normalize_rin(value) is not None)


def test_only_none_states_nothing() -> None:
    """One coercion, so two readers cannot disagree about the same value.

    ``docket_reference_as_stated`` read ``str(value)`` while its own helper
    ``normalize_regsgov_identifier`` read ``str(value or "")``; the falsy
    integer 0 therefore stated "0" to one and nothing to the other, about the
    identical input. Only ``None`` states nothing now.
    """

    assert docket_reference_as_stated(0) == "0"
    assert normalize_regsgov_identifier(0) == "0"
    assert normalize_rin(0) is None
    for stated_nothing in (None,):
        assert docket_reference_as_stated(stated_nothing) == ""
        assert normalize_regsgov_identifier(stated_nothing) is None
        assert normalize_rin(stated_nothing) is None


def test_null_sentinels_state_nothing() -> None:
    """The spellings a stringified null leaves behind, and nothing wider.

    ``str(None)``, ``str(float("nan"))`` and JSON's ``null`` are the three,
    plus the empty string. The set is deliberately case-sensitive: no
    case-variant spelling ("NULL", "NaN") occurs in any of the four pinned
    columns, so widening it would only risk swallowing a real reference.
    """

    for sentinel in ("", "None", "nan", "null", None):
        assert docket_reference_as_stated(sentinel) == ""
    assert docket_reference_as_stated("Docket No.") == ""
    assert docket_reference_as_stated("Docket Nos.") == ""
    assert docket_reference_as_stated("FSIS-2025-0012") == "FSIS-2025-0012"


# --------------------------------------------------------------------------- #
# One label vocabulary, read by the column reader and the prose reader alike.


def test_one_label_vocabulary_serves_both_readers() -> None:
    """The prose reader and the column reader must read one label the same way.

    They drifted: the column reader learned ``Docket #:`` and ``Docket -``
    while the inline pattern still allowed a single ``[:#]``, and the column
    reader spelled the counter word ``no\\.?|nos\\.?`` -- an alternation whose
    first branch wins, so "Docket Nos." stripped to "s.". One vocabulary,
    written once, read by both. Measured over the 608,758 distinct docket
    references: +939 distinct (+1,122 occurrences) resolved by the column
    reader, none lost, none changed; +37 distinct seen by the prose reader.

    The specimens below are ones both readers can express. Where their
    grammars differ -- an office segment between year and sequence -- see
    :func:`test_the_prose_reader_and_the_column_reader_are_not_merged`.
    """

    for stated, identifier in (
        ("Docket Nos. OSHA-2025-0006", "OSHA-2025-0006"),
        ("Dockets No. FMCSA-2007-28043", "FMCSA-2007-28043"),
        ("Docket IDs OCC-2020-0033", "OCC-2020-0033"),
        ("Docket #: EPA-R10-OAR-2014-0808", "EPA-R10-OAR-2014-0808"),
        ("Docket - FAA-2019-0001", "FAA-2019-0001"),
        ("Docket. No. AMS-FTPP-20-0088", "AMS-FTPP-20-0088"),
        ("Docket No.: EPA-HQ-OAR-2004-0015", "EPA-HQ-OAR-2004-0015"),
        ("Docket No: FAA-2019-0001", "FAA-2019-0001"),
    ):
        assert normalize_docket_reference(stated) == identifier, stated
        assert identifier in _dockets(stated), stated
    # Plural labels the column reader used to strip to "s." and refuse. Their
    # office segments put them beyond the prose grammar; see the next test.
    assert normalize_docket_reference("Docket Nos. FDA-2025-E-0162") == "FDA-2025-E-0162"
    assert normalize_docket_reference("DOCKET #: RBS-22-BUSINESS-0021") == "RBS-22-BUSINESS-0021"


def test_the_label_word_is_never_minted_as_the_organization() -> None:
    """A label is presentation; it cannot become part of what it presents.

    "Docket Number-NASA-2023-0005" resolved to organization NUMBER, because
    the label pattern's punctuation class did not admit the hyphen the agency
    wrote and its counter word fell back to being read as an agency code. The
    column reader no longer reads any reference that way; the prose reader
    still does for 7 distinct references (9 occurrences), and the paragraph
    below is why that is the longest-claim fence rather than this defect.

    The prose reader still prefers NUMBER-NASA-2023-0005 here, and that is
    the longest-claim fence outranking the label rather than the label rule
    failing: read as running text, "Number-NASA-2023-0005" is a longer claim
    than "NASA-2023-0005", and the fence that prefers it is the one that
    stops a short claim from splitting a real identifier. The column reader
    is the one asked about a docket field, and it now answers correctly.
    """

    assert normalize_docket_reference("Docket Number-NASA-2023-0005") == "NASA-2023-0005"
    assert normalize_docket_reference("NASA Docket Number-NASA-2026-0100") == "NASA-2026-0100"
    assert normalize_docket_reference("Docket Number-DHS-2022-0018") == "DHS-2022-0018"
    assert _dockets("Docket Number-NASA-2023-0005") == ["NUMBER-NASA-2023-0005"]


def test_a_label_token_is_a_whole_word() -> None:
    """ "Doc" is a label only where "doc" is a word.

    Unbounded, ``doc\\.?`` ate the head of any word starting "doc" and minted
    what was left as an agency: "Document-2021-0317" became docket
    UMENT-2021-0317, and the unbounded label read 3,234 distinct references
    (4,819 occurrences) differently from the bounded one ("NASA Document
    Number: 26-041" -> "ument Number: 26-041"). Bounded, nothing is minted
    from either -- the cap
    refuses the eight-letter word outright, which is the refusal that was
    always intended.
    """

    assert _dockets("Document-2021-0317") == []
    assert _dockets("Doctrine-2021-0317") == []
    assert docket_reference_as_stated("NASA Document Number: 26-041") == ("NASA Document Number: 26-041")
    # "doc" IS a label when it stands alone, however it is punctuated, and a
    # short word that merely begins with it is an agency like any other.
    assert normalize_docket_reference("Doc. No. AMS-SC-24-0046") == "AMS-SC-24-0046"
    assert _dockets("Docs-2021-0317") == ["DOCS-2021-0317"]


def test_the_counter_word_is_not_fenced_to_a_whole_word() -> None:
    """The label noun is a whole word; its counter word cannot be.

    Fencing it the same way -- "No" must not be followed by a letter -- was
    tried and measured: it refuses "Docket No.CDC-2018-0075", where the
    agency wrote the counter word's own period straight against the
    identifier. 239 references in the docket column are written that way, and
    90 of them resolve to a real docket only because the fence is off. The
    fence is off deliberately, and this is the test that says so.
    """

    assert normalize_docket_reference("Docket No.CDC-2018-0075") == "CDC-2018-0075"
    assert normalize_docket_reference("Docket No.CPSC-2009-0108") == "CPSC-2009-0108"
    # EL02-65-005 is a FERC docket, so it is named as one rather than read as
    # a Regulations.gov docket; what this line still proves is that the label
    # came off before the value was judged.
    assert numbering_system("Docket No.EL02-65-005") is NumberingSystem.FERC_DOCKET


def test_the_label_is_presentation_not_identity() -> None:
    text = "Docket No. FSIS-2025-0012"
    candidates = detect_identifier_shapes(text)
    assert [c.value for c in candidates] == ["FSIS-2025-0012"]
    start, end = candidates[0].span
    assert text[start:end] == "FSIS-2025-0012"


def test_a_value_that_is_already_an_identifier_is_never_label_stripped() -> None:
    """Strip-then-validate, in that order only.

    A docket whose organization is literally "DOCKET" must survive its own
    name, and the prose reader must not offer a mutilated shorter claim
    beside the whole one.
    """

    assert normalize_docket_reference("FDA-2011-N-0002") == "FDA-2011-N-0002"
    assert normalize_docket_reference("DOCKET-2011-0004") == "DOCKET-2011-0004"
    assert _dockets("Docket-2011-0004") == ["DOCKET-2011-0004"]


def test_docket_stripping_never_mutilates_a_numbered_label() -> None:
    """ "MM Docket No. 98-213" is an FCC docket the shape cannot express.

    Turning it into "98-213" would key a docket on a number the label was
    presenting. The letter-opening rule refused 5,214 of 5,506 mutilated
    references at the cost of no real docket.
    """

    assert normalize_docket_reference("DHS Docket No. USCIS-2025-0004") == "USCIS-2025-0004"
    assert normalize_docket_reference("MM Docket No. 98-213") is None
    assert normalize_docket_reference("Docket No. FSIS-2025-0012") == "FSIS-2025-0012"
    assert normalize_docket_reference("Docket #: 1") is None
    assert normalize_docket_reference("RELEASE NO. 33-8176") is None


def test_a_docket_must_end_on_the_sequence_it_is_keyed_by() -> None:
    """The suffixed spellings keep refusing: the shape must end on digits, or on one of the five closed tokens.

    "Internal Agency Docket No. FEMA-1971-DR" (2,918 distinct references) is
    refused for the same reason, not for the two words in front of its label.
    RefSpec's copy of this test also expected "GIPSA-2008-FGIS-0002-NONRULEMAKING"
    refused; the prose reader already read that family as the docket the
    publisher states, and since 2026-09-23 the column reader does too (see the
    segment tests at the end of this file).
    """

    assert normalize_docket_reference("GIPSA-2008-FGIS-0002-NONRULEMAKING") == "GIPSA-2008-FGIS-0002-NONRULEMAKING"
    assert normalize_docket_reference("Internal Agency Docket No. FEMA-1971-DR") is None


def test_the_docket_organization_cap_stops_english_words() -> None:
    """ "documentation-2021-0317" must not mint docket DOCUMENTATION-2021-0317.

    The cap is the prose reader's, not the column reader's: in a docket
    column the column itself declares intent, so the long compound is kept.
    """

    assert _kinds("see documentation-2021-0317 for details") == []
    assert ("docket", "EPA-HQ-OAR-2021-0317") in _kinds("EPA-HQ-OAR-2021-0317")
    assert normalize_docket_reference("documentation-2021-0317") == "DOCUMENTATION-2021-0317"


def test_a_label_licenses_the_two_digit_year_for_the_prose_reader() -> None:
    """Unlabeled "AMS-SC-24-0046" is indistinguishable from "GAO-26-9060".

    In prose it therefore stays undetected rather than guessed. In a docket
    column the field itself is the license, so the two-digit year is read --
    12,076 distinct references (17,284 occurrences) of the "AMS-SC-25-0848"
    form would otherwise be thrown away. The two readers answer different
    questions; this is the sentence that says so.

    The "CP26-20-000" form is read here too, but as a FERC docket: it fits
    this shape and belongs to another registry, and regulations.gov answers
    400 for it. Naming the system it does belong to keeps the value without
    misfiling it.
    """

    assert ("docket", "AMS-SC-24-0046") in _kinds("Doc. No. AMS-SC-24-0046")
    assert _kinds("per AMS-SC-24-0046 and GAO-26-9060") == []
    assert normalize_docket_reference("AMS-SC-25-0848") == "AMS-SC-25-0848"
    assert normalize_docket_reference("GAO-26-9060") == "GAO-26-9060"


def test_an_office_segment_is_read_when_it_is_letters_and_only_then() -> None:
    """The "N" in "FDA-2026-N-0008" is an office segment, and it is letters.

    Both forms are real Regulations.gov dockets, and the publisher says so:
    its API answered 200 for FDA-2026-N-0008 and for EERE-2022-BT-OT-0004 on
    2026-08-22, and the Federal Register API calls each one an "agency
    docket". The office may be more than one segment -- DOE writes a program
    and a rulemaking type ("BT", "OT") -- so the run is read whole.

    Letters-only is the whole of the fence, and it is what keeps this segment
    from swallowing a Regulations.gov document id: admitted with digits,
    "EPA-HQ-OAR-2021-0317-0001" would read as organization-year-office-
    sequence and a document would become a docket.
    """

    assert ("docket", "FDA-2026-N-0008") in _kinds("FDA-2026-N-0008")
    assert ("docket", "FDA-2026-N-0008") in _kinds("Docket No. FDA-2026-N-0008")
    assert ("docket", "EERE-2022-BT-OT-0004") in _kinds("see EERE-2022-BT-OT-0004 for the record")
    assert _kinds("EPA-HQ-OAR-2021-0317-0001") == [("regulations_gov_document", "EPA-HQ-OAR-2021-0317-0001")]
    # A cell that states two dockets is prose, and the two readers answer it
    # as what each of them is: the column refuses it whole, the prose reader
    # reads both. 781 distinct references in the docket column read this way.
    stated_twice = "Docket Nos. FDA-2025-E-0501 and FDA-2025-E-0502"
    assert normalize_docket_reference(stated_twice) is None
    assert _dockets(stated_twice) == ["FDA-2025-E-0501", "FDA-2025-E-0502"]


def test_an_office_segment_is_carried_in_the_structure_or_not_at_all() -> None:
    """``components`` is authoritative, so a stated office appears in it.

    An office segment that is read but not reported would leave a value its
    own components cannot reconstruct. An office nobody stated is not
    reported as empty either -- an optional segment states itself or says
    nothing, which is also what keeps every docket answered before this rule
    existed serialising to exactly the same facts.
    """

    stated = detect_identifier_shapes("EERE-2022-BT-OT-0004")[0]
    assert stated.components == {
        "organization": "EERE",
        "year": "2022",
        "office": "BT-OT",
        "sequence": "0004",
    }
    unstated = detect_identifier_shapes("FSIS-2025-0012")[0]
    assert unstated.components == {"organization": "FSIS", "year": "2025", "sequence": "0012"}
    assert "office" not in unstated.as_dict()["components"]


def test_the_prose_reader_and_the_column_reader_are_not_merged() -> None:
    """Two questions, two answers, and the gap between them is measured.

    The office segment above is the part of that gap the corpus witnesses
    most. Measured over the 608,758 distinct docket references on 2026-08-22,
    reading it moved 15,583 distinct references (26,188 occurrences) from no
    prose claim to at least one, and nothing else in any of the four pinned
    columns changed any answer: 14,802 of those references are ones the
    column reader already resolved and the prose reader could not see, and
    the other 781 are cells stating more than one docket ("Docket Nos.
    FDA-2025-E-0501 and FDA-2025-E-0502"), which the column reader refuses
    whole because a validator answers "is" and not "contains", and which the
    prose reader exists to read.

    What is left is not an oversight. 63,249 distinct (70,470 occurrences),
    re-measured 2026-08-22, still resolve in the column and stay invisible in
    prose -- down from the 63,490 (70,749) stated the day the office segment
    above was written. 17 distinct (17 occurrences) of that movement is the
    same segment mirrored onto the Regulations.gov document grammar, which
    reads a six-digit document sequence like "EPA-R04-OAR-2005-AL-0003-200539"
    for the first time; see
    :func:`test_an_office_segment_also_reaches_a_six_digit_document_sequence`
    and :func:`test_the_office_segment_is_measured_over_the_real_docket_column`
    for that count and where it comes from. The rest of the movement is the
    corpus itself, read fresh today rather than diffed against that day's
    snapshot -- the same drift the corrector's own docstring already names
    for the RIN roster. Every reference still standing in the gap is a shape
    a label would have to license: a sequence outside three to five digits
    ("EPA-HQ-OAR-2021-0", "FR-6617-N-01"), a two-digit year with no label, or
    an organization that does not open on two to six letters. Reading those
    in running text means reading "B-55-2025" out of a sentence. The gap is
    pinned here as it stands.
    """

    assert normalize_docket_reference("EPA-HQ-OAR-2021-0") == "EPA-HQ-OAR-2021-0"
    assert _kinds("EPA-HQ-OAR-2021-0") == []
    assert normalize_docket_reference("Docket No. FR-6617-N-01") == "FR-6617-N-01"
    assert _kinds("Docket No. FR-6617-N-01") == []
    assert normalize_docket_reference("B-55-2025") == "B-55-2025"
    assert _kinds("B-55-2025") == []


def test_an_office_segment_moves_a_decomposed_docket_to_a_document() -> None:
    """ "EERE-2019-BT-PET-0019-0008" is a document, and it is now read as one.

    Before this rule, the document grammar had no group for "BT-PET" to
    fill, so the docket grammar's own organization group -- which absorbs
    any alnum continuation segment, not only a letters-only run -- swallowed
    year, office and docket sequence together instead: organization
    "EERE-2019-BT-PET", "year" 0019, "sequence" 0008. It was already a right
    answer -- docket EERE-2019-BT-PET-0019, document 0008 -- so mirroring the
    office segment onto the document grammar corrects the decomposition
    rather than admitting anything new. The Federal Register API lists two
    documents under this exact docket id, 2020-14400 and 2019-27630,
    confirmed 2026-08-22. This is one of 11 references (13 occurrences) the
    pinned docket column states this way; the full set is named in
    :func:`test_the_office_segment_is_measured_over_the_real_docket_column`.
    """

    candidates = detect_identifier_shapes("EERE-2019-BT-PET-0019-0008")
    assert [c.kind for c in candidates] == [IdentifierKind.REGULATIONS_GOV_DOCUMENT]
    assert candidates[0].components == {
        "organization": "EERE",
        "year": "2019",
        "office": "BT-PET",
        "docket_sequence": "0019",
        "document_sequence": "0008",
    }
    assert _dockets("EERE-2019-BT-PET-0019-0008") == []
    # A labelled specimen from the same population: the label sits outside
    # the value the office segment reads, so it moves the same way.
    assert [c.kind for c in detect_identifier_shapes("Docket No. EERE-2009-BT-TP-0016-0017")] == [
        IdentifierKind.REGULATIONS_GOV_DOCUMENT
    ]


def test_an_office_segment_also_reaches_a_six_digit_document_sequence() -> None:
    """A second effect the same rule buys, and it is not a rewrite of anything.

    "EPA-R04-OAR-2005-AL-0003-200539" was invisible to both readers before
    this rule -- not even a wrong docket answer, unlike the reference above.
    The docket grammar's sequence tops out at five digits and cannot consume
    a six-digit tail, and the document grammar had nowhere for the state
    code "AL" to go, so neither grammar matched anything at all. Confirmed
    against the Federal Register API 2026-08-22: docket EPA-R04-OAR-2005-AL-
    0003, document 200539, is document E6-907, "Approval and Promulgation of
    Implementation Plans and Designation of Areas for Air Quality Planning
    Purposes; Alabama; Redesignation of the Birmingham 8-Hour Ozone
    Nonattainment Area to Attainment for Ozone" (2006-01-25). 36 references
    (36 occurrences) in the pinned docket column gain a prose answer this
    way -- named by count, not individually, in
    :func:`test_the_office_segment_is_measured_over_the_real_docket_column`.
    """

    candidates = detect_identifier_shapes("EPA-R04-OAR-2005-AL-0003-200539")
    assert [c.kind for c in candidates] == [IdentifierKind.REGULATIONS_GOV_DOCUMENT]
    assert candidates[0].components == {
        "organization": "EPA-R04-OAR",
        "year": "2005",
        "office": "AL",
        "docket_sequence": "0003",
        "document_sequence": "200539",
    }
    assert _dockets("EPA-R04-OAR-2005-AL-0003-200539") == []


def test_the_frdoc_family_is_a_docket_without_a_year() -> None:
    """Every agency holds one "AGENCY_FRDOC_0001" docket on Regulations.gov
    for its Federal Register documents (ACF_FRDOC_0001 is real and
    navigable; 72,404 catalog document rows carry the family). The literal
    FRDOC token is the anchor the missing year would otherwise provide --
    an arbitrary year-less compound still refuses."""

    assert normalize_docket_reference("DOT_FRDOC_0001") == "DOT_FRDOC_0001"
    assert normalize_docket_reference("acf_frdoc_0001") == "ACF_FRDOC_0001"
    assert normalize_docket_reference("Docket No. CMS_FRDOC_0001") == "CMS_FRDOC_0001"
    assert normalize_docket_reference("DOT_SOMEDOC_0001") is None


# --------------------------------------------------------------------------- #
# Federal Register document numbers: four forms, one mintable.


def test_a_modern_document_number_may_carry_a_short_or_padded_sequence() -> None:
    """The publisher mints three-, four-, and five-digit sequences, and pads
    some years and not others. All three are real, confirmed against the
    Federal Register's own API on 2026-08-22: 2010-5997 published 2010-03-19,
    2011-237 published 2011-01-11, 2012-00019 published 2012-01-04. The
    five-digit-only shape refused 28,862 of the 480,566 modern-form numbers
    in the pinned corpus."""

    for value in ("2010-5997", "2011-237", "2012-00019", "2024-12345"):
        assert is_federal_register_document_number(value), value


def test_padding_is_part_of_the_identifier_and_is_never_stripped() -> None:
    """A padded number and its unpadded spelling are different strings, and
    the publisher issues only one of them: across the 480,566 modern-form
    values not one padded number has an unpadded twin. Normalizing the
    padding would invent a spelling no publisher minted, so the literal
    string is the key."""

    padded = "2012-00019"
    assert is_federal_register_document_number(padded)
    assert normalize_regsgov_identifier(padded) == padded
    assert docket_reference_as_stated(padded) == padded
    assert detect_identifier_shapes(padded)[0].value == padded


def test_a_two_digit_sequence_is_not_a_document_number() -> None:
    """The floor is three digits: the shape still has to state something."""

    assert not is_federal_register_document_number("2011-23")
    assert not is_federal_register_document_number("2011-2")


def test_the_four_recognised_forms_are_detected_whole_and_exactly_once() -> None:
    """Legacy, correction and republication numbers are official identifiers.

    The republication convention is stated by the publisher in the documents
    themselves: R1-2010-13257 is "Federal Property Suitable as Facilities To
    Assist the Homeless; Republication", published 2010-06-04. R1-10679 also
    satisfies the legacy form, so two grammars claim the identical span --
    exactly one candidate must come back.

    Each form is named in ``_FR_DOCUMENT_FORMS``, and the names carry a
    specimen here so they mean something a check can break on: a name nobody
    can produce a witness for is a name that has stopped being true.
    """

    from spicy_docs.interpretation.identifier_shapes import _FR_DOCUMENT_FORMS

    witness = {
        "modern": "2026-13078",
        "correction": "C1-2026-13078",
        "republication": "R1-2010-13257",
        "legacy": "E7-21559",
    }
    assert witness.keys() == {name for name, _ in _FR_DOCUMENT_FORMS}
    for name, form in _FR_DOCUMENT_FORMS:
        assert re.fullmatch(form, witness[name]), name

    for value in (*witness.values(), "R1-10679"):
        candidates = detect_identifier_shapes(value)
        assert [c.value for c in candidates] == [value], value
        assert candidates[0].kind is IdentifierKind.FEDERAL_REGISTER_DOCUMENT
        assert candidates[0].span == (0, len(value))

    # The one documented overlap: R1-10679 satisfies two forms at once, which
    # is why detection deduplicates identical claims rather than returning two.
    forms = dict(_FR_DOCUMENT_FORMS)
    assert re.fullmatch(forms["republication"], "R1-10679")
    assert re.fullmatch(forms["legacy"], "R1-10679")


def test_only_the_modern_form_is_mintable() -> None:
    """The other three are real, and outside the mintable lexical space.

    ``FEDERAL_REGISTER_DOCUMENT_NUMBER`` is that space, spelled once and
    shared by the detector and the validator so the two cannot drift.
    """

    assert re.fullmatch(FEDERAL_REGISTER_DOCUMENT_NUMBER, "2026-13078")
    for value in ("E7-21559", "C1-2026-13078", "R1-2010-13257", "R1-10679"):
        assert not is_federal_register_document_number(value), value


def test_the_recognised_forms_are_chosen_subsets_of_a_real_format() -> None:
    """What this module refuses is not thereby malformed.

    Every specimen below answered 200 from the Federal Register's own API on
    2026-08-22 and is a real published document, and every one falls outside
    the forms above: Z9-802 and E9-654 carry a three-digit tail, E9-23 two,
    Z9-9 one; X10-11220 opens on a two-digit prefix and X09-101207 closes on
    a six-digit tail; C1-2012-19 is a correction whose ``correction_of`` is
    2012-00019; E3-2013-2261 is a HUD notice wearing a legacy prefix over a
    modern body. 10,340 letter-opening document numbers go unread this way.

    The refusal is a recall decision, not a judgement about the corpus, and
    this test exists so that nobody re-derives "these must be malformed" from
    the silence.
    """

    for real_but_unread in (
        "Z9-802",
        "E9-654",
        "E9-23",
        "Z9-9",
        "X10-11220",
        "X09-101207",
        "C1-2012-19",
        "C1-2012-2091",
        "E3-2013-2261",
    ):
        assert _kinds(real_but_unread) == [], real_but_unread
        assert not is_federal_register_document_number(real_but_unread), real_but_unread


def test_a_real_rin_outside_the_shape_is_refused_not_repaired() -> None:
    """The RIN shape is the Unified Agenda's universe, not the world's.

    All 46,547 Unified Agenda RINs conform to it and none is excepted, so it
    is the right fence for the roster it guards. It is not a published
    universal format -- none exists -- and five real RINs in the Federal
    Register's own ``regulation_id_numbers`` field fall outside it, each
    confirmed against that API on 2026-08-22: NOAA's five-character inseason
    suffixes, and three that run digit-digit-letter-letter.

    They are refused, and the corrector must not invent a repair for them
    either: nothing in the roster is one named operator away.
    """

    roster = {"0301-AA00", "1018-BI73", "2060-AV45"}
    for real_but_unminted in ("0648-XD990", "0648-XC705", "3090-00XX", "1115-09AE", "2070-78AB"):
        assert not is_regulation_identifier_number(real_but_unminted), real_but_unminted
        assert corrected_rin(real_but_unminted, roster) is None, real_but_unminted


def test_a_two_digit_year_document_number_stays_undetected() -> None:
    """396,035 of the 1,004,233 distinct document numbers open on a digit and
    are refused: "94-12345" is the pre-2000 form, and unlabeled it is
    indistinguishable from "MM Docket No. 98-213" and from a release number.
    Reading it would require a label the column does not carry, so the
    refusal is doctrine, not a gap to be closed quietly."""

    assert _kinds("94-12345") == []
    assert _kinds("2013-58") == []
    assert not is_federal_register_document_number("94-12345")


# --------------------------------------------------------------------------- #
# The column license: REF-052/REF-054. Bare-legacy and four letter-opening
# families the prose reader above refuses -- and keeps refusing -- become
# readable when ``column_licensed=True`` states the value arrived from a
# ``document_number`` field. Every positive specimen below is read against
# the publisher's own printed page in ``docs/decisions.md``'s REF-052 record;
# every negative is a shape the pinned column does not carry.


def test_prose_detection_is_unwidened_by_the_column_license() -> None:
    """The column license is a second question, never a softer version of the
    first one. Every specimen the prose reader already refuses above is
    refused identically here -- ``detect_identifier_shapes`` takes no
    argument to loosen, and ``is_federal_register_document_number`` without
    the flag answers exactly as it did before this cycle."""

    for value in ("Z9-802", "E9-654", "E9-23", "Z9-9", "X10-11220", "X09-101207", "E3-2013-2261", "09-19806"):
        assert detect_identifier_shapes(value) == [], value
        assert not is_federal_register_document_number(value), value
        assert not is_federal_register_document_number(value, column_licensed=False), value


def test_the_bare_legacy_shape_is_licensed_by_the_column() -> None:
    """§1.2, now read from this module rather than ``iri_minting``.

    "09-19806" is the Federal Trade Commission's "CSE, Inc., et al." consent
    notice, Federal Register Vol. 74 No. 159 p.41908 (2009-08-19); its own
    printed colophon reads "[FR Doc. 09-19806 Filed 8-18-09; 1:15 pm]"
    verbatim. "00-10" is a real airworthiness directive of 2000-01-04 -- once
    the named refusal at :data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`,
    now read by REF-056's sibling production
    :data:`~refspec.registry.identifier_shapes._FR_BARE_LEGACY_SHORT_TAIL`,
    exercised directly in
    ``test_the_bare_legacy_short_tail_family_is_column_licensed`` below.
    """

    assert re.fullmatch(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER, "09-19806")
    assert is_federal_register_document_number("09-19806", column_licensed=True)
    assert is_federal_register_document_number("00-10", column_licensed=True)


def test_the_three_digit_and_shorter_tail_family_is_column_licensed() -> None:
    """The legacy form's own shape with the tail widened down to one to three
    digits -- exactly the axis rc16 widened the modern form along.

    E9-654 is real: Federal Register Vol. 74 No. 21 p.5921 (2009-02-03),
    printed colophon "[FR Doc. E9-654 Filed 2-2-09; 8:45 am]", on the same
    page as "[FR Doc. E9-2239 Filed 2-2-09; 8:45 am]" -- an ordinary
    four-digit sibling in the identical numbering series, published the same
    day. The short tail is the low end of an ordinary sequence, and 5,829
    values in the pinned column take this shape.

    "Z99-9" -- a two-digit prefix with a one-digit tail -- is the negative:
    zero values of that shape exist in the pinned column, so it stays
    refused rather than admitted on the strength of a name alone.
    """

    assert is_federal_register_document_number("E9-654", column_licensed=True)
    assert is_federal_register_document_number("Z9-9", column_licensed=True)
    assert not is_federal_register_document_number("Z99-9", column_licensed=True)


def test_the_two_digit_prefix_family_is_column_licensed() -> None:
    """A letter, two digits, then the legacy form's own five-digit tail.

    X10-11220 is real (Vol. 75 No. 243 p.79449, 2010-12-20), read end to end
    against the publisher's PDF as "Introduction to The Regulatory Plan and
    the Unified Agenda of Federal Regulatory and Deregulatory Actions" -- the
    composite front-matter section opening that fall's whole special
    supplement, not a per-document filing with its own colophon. It is still
    the publisher's own ``document_number`` for the section. 4,195 values in
    the pinned column take this shape, all with a five-digit tail.

    "X10-654" -- the same two-digit prefix with a three-digit tail -- is the
    negative: no two-digit-prefix value in the pinned column carries a
    three- or four-digit tail.
    """

    assert is_federal_register_document_number("X10-11220", column_licensed=True)
    assert not is_federal_register_document_number("X10-654", column_licensed=True)


def test_the_six_digit_tail_family_is_column_licensed() -> None:
    """A letter, exactly two digits, then a six-digit tail.

    X09-101207 is real (Vol. 74 No. 233 p.64213, 2009-12-07), read end to end
    against the publisher's PDF as the Fall 2009 Regulatory Plan itself -- 33
    pages closing with FEMA's "Special Community Disaster Loans Program"
    entry at p.64245, no colophon on either bounding page, still the
    publisher's own id. 206 values in the pinned column take this shape.

    "E9-654321" -- a one-digit prefix with a six-digit tail -- is the
    negative: zero values of that shape exist in the pinned column, so the
    family stays exactly as wide as what was measured.
    """

    assert is_federal_register_document_number("X09-101207", column_licensed=True)
    assert not is_federal_register_document_number("E9-654321", column_licensed=True)


def test_the_legacy_over_modern_body_hybrid_is_column_licensed() -> None:
    """A letter and one digit, then the modern form's own body whole.

    E3-2013-2261 is real (Vol. 78 No. 22 p.7443, 2013-02-01, "Request for
    Comment on the Redesign of the American Housing Survey"); its own printed
    colophon -- "[FR Doc. E3-2013-2261 Filed 1-31-13; 8:45 am]" -- sits in
    the same place and style as every ordinary document's on the same page.
    It is the only value in the pinned column that takes this shape.

    "C1-2012-19" is the negative: it is one of the 99 short-tail corrections
    REF-054 names and keeps refused (its own ``correction_of`` is
    2012-00019), not a member of this family -- the hybrid excludes C and R
    prefixes by construction, because a C-prefixed value here is that
    deferred population and an R-prefixed one is already read by the
    republication form.
    """

    assert is_federal_register_document_number("E3-2013-2261", column_licensed=True)
    assert not is_federal_register_document_number("C1-2012-19", column_licensed=True)


# --------------------------------------------------------------------------- #
# The widening cycle: REF-056. Two more column-licensed-only productions,
# each a new named constant rather than a rewrite of an existing one, so the
# counts REF-052/REF-054 already published (394,128 bare-legacy; 10,231
# letter-opening) stay exactly what they were. Every positive specimen below
# is read against the publisher's own PDF in
# research/evidence/fr-short-tails-2026-08-31/.


def test_the_bare_legacy_short_tail_family_is_column_licensed() -> None:
    """The bare-legacy shape's own floor, widened to one and two digits.

    "00-1" is EPA's Amino/Phenolic Resins NESHAP (65 FR 3276, 2000-01-20);
    "00-10" is the FAA airworthiness directive named above. Each carries its
    own printed colophon in the ordinary place. "93-54" witnesses a
    sub-cluster worth naming on its own: filed 1994-01-03 for the next day's
    issue, it still carries the outgoing year's two-digit token, which is why
    a "93-"-prefixed value exists at all next to an era documented as opening
    1994-01-03. 1,370 values in the pinned column take this shape: 112 with a
    one-digit tail, 1,258 with two.

    "94-1234567" -- a seven-digit tail -- is the negative: the ceiling
    REF-052 measured (six digits) is untouched by this widening, only the
    floor moved.
    """

    assert is_federal_register_document_number("00-1", column_licensed=True)
    assert is_federal_register_document_number("00-10", column_licensed=True)
    assert is_federal_register_document_number("93-54", column_licensed=True)
    assert not is_federal_register_document_number("94-1234567", column_licensed=True)
    # Unlicensed, all three stay exactly as unread as the wider bare-legacy
    # shape already is -- REF-056 widens the column license, not the prose.
    for value in ("00-1", "00-10", "93-54"):
        assert _kinds(value) == [], value
        assert not is_federal_register_document_number(value), value


def test_the_modern_short_tail_family_is_column_licensed() -> None:
    """The modern shape's own floor, widened to one and two digits --
    admitted to the partner hatch only. rulespec's own mintable space
    (``FEDERAL_REGISTER_DOCUMENT_NUMBER``, three to five digits) is untouched
    by this widening; only what the column licenses moved.

    "2010-1" is an SEC notice of application (75 FR 1007-1009, 2010-01-07),
    whose colophon on page 1009 sits beside two ORDINARY three-digit-tail
    numbers, "2010-117" and "2010-113" -- the comparison that shows a short
    tail is the low end of one numbering series rather than a different kind
    of string. "2010-10" is a DOE notice (75 FR 983, same issue), sharing its
    page with "2010-9" and "2010-36". Each carries its own printed colophon
    in the ordinary place.

    "2013-58" is the sole specimen outside the 2010-2012 cluster: filed
    2013-01-02 at 4:15 pm, printed on 78 FR 908 one page after a
    2012-tokened document ("2012-31431", filed 1-4-13) in the same issue.
    The pair establishes only that the year token follows neither date the
    page prints; what decides it is not established, and this ruling does not
    need it -- see the note beside ``_FR_MODERN_SHORT_TAIL``. 286 values in
    the pinned column take this shape: 27 with a one-digit tail, 259 with
    two.
    """

    assert is_federal_register_document_number("2010-1", column_licensed=True)
    assert is_federal_register_document_number("2010-10", column_licensed=True)
    assert is_federal_register_document_number("2013-58", column_licensed=True)
    # Unlicensed, prose detection is unchanged -- this is the same value
    # ``test_a_two_digit_year_document_number_stays_undetected`` already
    # reads as prose-undetected.
    for value in ("2010-1", "2010-10", "2013-58"):
        assert _kinds(value) == [], value
        assert not is_federal_register_document_number(value), value
    # Three digits and up was already rulespec's own space, unmoved by this
    # ruling.
    assert is_federal_register_document_number("2010-100")


def test_no_federal_register_production_claims_another_ones_specimen() -> None:
    """Disjointness as a test rather than as a comment.

    ``_FR_COLUMN_LETTER_FORMS`` argues its four members are disjoint "BY
    CONSTRUCTION, not by census", and REF-056's two new productions repeat
    the argument for themselves. An argument in a comment is not a check
    that breaks when it is violated, and this is the check: every Federal
    Register production the module carries, prose and column alike, offered
    every other production's own positive specimen.

    Two overlaps are REAL, both pre-existing, both between prose forms and
    both harmless -- they are asserted here rather than hidden, because a
    test that expected zero overlaps would have to launder them:

    - "R1-10679" and "R1-1234" satisfy the republication form AND the legacy
      form;
    - "R1-123" satisfies the republication form AND the letter-opening short
      tail.

    Neither is a defect, for the reason ``_FR_DOCUMENT_FORMS``'s own comment
    gives: the alternation is ordered, republication precedes legacy, and
    both branches read the identical characters as the identical value, so
    which one wins cannot change any answer. The corpus witnesses the first
    overlap 32 times (R0-12376, R1-10679, ...) and the second not at all --
    it is lexically possible and stays asserted so a future edit that makes
    it matter is not silent.

    Everything else claims exactly its own specimens, which is what makes
    the census's buckets a partition instead of a priority list.
    """

    productions: dict[str, re.Pattern[str]] = {
        name: re.compile(pattern) for name, pattern in identifier_shapes._FR_DOCUMENT_FORMS
    }
    productions.update(
        {
            "bare-legacy": identifier_shapes._FR_BARE_LEGACY,
            "bare-legacy-short-tail": identifier_shapes._FR_BARE_LEGACY_SHORT_TAIL,
            "modern-short-tail": identifier_shapes._FR_MODERN_SHORT_TAIL,
            "letter-short-tail": identifier_shapes._FR_LETTER_SHORT_TAIL,
            "two-digit-prefix": identifier_shapes._FR_TWO_DIGIT_PREFIX,
            "six-digit-tail": identifier_shapes._FR_SIX_DIGIT_TAIL,
            "legacy-over-modern-body": identifier_shapes._FR_LEGACY_OVER_MODERN_BODY,
        }
    )

    # The table is complete by construction rather than by attention: a
    # production added to the module without a row here fails immediately.
    # ``_FR_DOCUMENT`` is the anchored prose reader ASSEMBLED from the four
    # forms rather than a fifth one, and ``_FR_MODERN`` is the "modern" form
    # under its private name -- asserted, not assumed, on the next line.
    compiled = {
        name
        for name in dir(identifier_shapes)
        if name.startswith("_FR_") and isinstance(getattr(identifier_shapes, name), re.Pattern)
    }
    assert compiled - {"_FR_DOCUMENT", "_FR_MODERN"} == {
        "_FR_BARE_LEGACY",
        "_FR_BARE_LEGACY_SHORT_TAIL",
        "_FR_LEGACY_OVER_MODERN_BODY",
        "_FR_LETTER_SHORT_TAIL",
        "_FR_MODERN_SHORT_TAIL",
        "_FR_SIX_DIGIT_TAIL",
        "_FR_TWO_DIGIT_PREFIX",
    }
    assert identifier_shapes._FR_MODERN.pattern == productions["modern"].pattern

    #: Specimen -> the productions that may read it, and no others. Every
    #: value is one the pinned ``document_number`` column really carries,
    #: except the two marked below.
    expected: dict[str, set[str]] = {
        # modern: rulespec's own space, padded and unpadded.
        "2010-100": {"modern"},
        "2012-00019": {"modern"},
        # correction, republication, legacy -- the prose reader's own three.
        "C1-2009-21472": {"correction"},
        "R1-2010-13257": {"republication"},
        "E9-2239": {"legacy"},
        "C0-10087": {"legacy"},
        # bare-legacy, floor and six-digit ceiling.
        "09-19806": {"bare-legacy"},
        "94-120124": {"bare-legacy"},
        # REF-052's four letter-opening families.
        "E9-654": {"letter-short-tail"},
        "E9-23": {"letter-short-tail"},
        "Z9-9": {"letter-short-tail"},
        "X10-11220": {"two-digit-prefix"},
        "X09-101207": {"six-digit-tail"},
        "E3-2013-2261": {"legacy-over-modern-body"},
        # REF-056's two. These are the rows the widening had to earn: a
        # bare-legacy short tail must not become readable as a modern one,
        # and neither may reach into the letter-opening families.
        "00-1": {"bare-legacy-short-tail"},
        "00-10": {"bare-legacy-short-tail"},
        "93-54": {"bare-legacy-short-tail"},
        "2010-1": {"modern-short-tail"},
        "2010-10": {"modern-short-tail"},
        "2013-58": {"modern-short-tail"},
        # The two real overlaps, named. The first is corpus-witnessed 32
        # times; the second is lexical only.
        "R1-10679": {"republication", "legacy"},
        "R1-1234": {"republication", "legacy"},
        "R1-123": {"republication", "letter-short-tail"},
        # Refused by every production, and staying that way: REF-054's
        # short-tail correction, the ceiling above bare-legacy's six digits,
        # and the census's one non-identifier.
        "C1-2012-19": set(),
        "94-1234567": set(),
        "granule293": set(),
    }
    for value, names in expected.items():
        assert {name for name, p in productions.items() if p.fullmatch(value)} == names, value

    # Why the two overlaps are safe, rather than merely tolerated: the
    # alternation is ordered and republication comes first, so a first-match
    # read names it; and both branches return the identical value, so the
    # order could flip without moving an answer.
    order = [name for name, _ in identifier_shapes._FR_DOCUMENT_FORMS]
    assert order.index("republication") < order.index("legacy")
    for overlapping in ("R1-10679", "R1-1234", "R1-123"):
        first = next(name for name in order if productions[name].fullmatch(overlapping))
        assert first == "republication", overlapping
        assert _kinds(overlapping) == [("federal_register_document", overlapping)], overlapping


# --------------------------------------------------------------------------- #
# Arbitration between grammars that claim the same characters.


def test_the_precedence_table_arbitrates_one_measured_contest() -> None:
    """A Regulations.gov document contains a docket; the document must win.

    The contest is real and exact: the docket grammar reads
    "EPA-HQ-OAR-2021-0317-0001" whole, with the year absorbed into the
    organization, so length cannot separate the two claims. 56 distinct
    references in the docket column produce that exact tie. No other pair of
    kinds ties on any value in any of the four pinned columns -- in
    particular a correction number produces no docket claim at all, because
    "C1" is one letter where the organization needs two.
    """

    candidates = detect_identifier_shapes("see EPA-HQ-OAR-2021-0317-0001")
    assert [c.kind for c in candidates] == [IdentifierKind.REGULATIONS_GOV_DOCUMENT]
    correction = detect_identifier_shapes("C1-2026-13078")
    assert [c.kind for c in correction] == [IdentifierKind.FEDERAL_REGISTER_DOCUMENT]
    assert _dockets("C1-2026-13078") == []


def test_the_longest_claim_wins_over_any_stretch_of_text() -> None:
    """The sweep keeps the longest claim, then the most specific on a tie."""

    claims = [
        IdentifierCandidate(kind=IdentifierKind.DOCKET, value="B", span=(5, 15)),
        IdentifierCandidate(kind=IdentifierKind.RIN, value="A", span=(0, 10)),
        IdentifierCandidate(kind=IdentifierKind.DOCKET, value="C", span=(20, 24)),
    ]
    assert [c.value for c in keep_longest_then_most_specific(claims)] == ["A", "C"]
    assert keep_longest_then_most_specific([]) == []
    # A single claim starting at 0 is kept: the sweep's reach starts empty.
    lone = [IdentifierCandidate(kind=IdentifierKind.RIN, value="A", span=(0, 4))]
    assert keep_longest_then_most_specific(lone) == lone


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_detection_never_returns_two_claims_on_one_stretch(text: str) -> None:
    """Property: the kept claims are start-ordered and pairwise disjoint."""

    spans = [c.span for c in detect_identifier_shapes(text)]
    assert spans == sorted(spans)
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert end <= start


def test_a_candidate_serializes_to_its_own_facts() -> None:
    """A candidate serializes its own facts, omitting components when it states none."""
    candidate = detect_identifier_shapes("EPA-HQ-OAR-2021-0317-0001")[0]
    assert candidate.as_dict() == {
        "kind": "regulations_gov_document",
        "span": [0, 25],
        "value": "EPA-HQ-OAR-2021-0317-0001",
        "components": {
            "organization": "EPA-HQ-OAR",
            "year": "2021",
            "docket_sequence": "0317",
            "document_sequence": "0001",
        },
    }
    assert "components" not in detect_identifier_shapes("2026-13078")[0].as_dict()


def test_a_candidate_can_be_put_in_a_set() -> None:
    """``set(detect_identifier_shapes(text))`` raised ``TypeError``.

    The dataclass is frozen, so Python generated a ``__hash__`` over its
    fields -- and one of those fields is a mapping, which is unhashable, so
    every candidate carrying components was unhashable too. The candidates
    with no components hashed fine, which is why nothing noticed.

    Hashing now reads the same identity the detector's own deduplication
    reads, so the two cannot disagree about whether two claims are the same
    claim: equal candidates hash equal, and a set collapses exactly the
    duplicates ``detect_identifier_shapes`` collapses.
    """

    candidates = detect_identifier_shapes("Docket No. FSIS-2025-0012 and EPA-HQ-OAR-2021-0317-0001")
    assert {c.kind for c in candidates} == {IdentifierKind.DOCKET, IdentifierKind.REGULATIONS_GOV_DOCUMENT}
    assert len(set(candidates)) == len(candidates)
    assert set(candidates) == set(candidates)

    twin = IdentifierCandidate(
        kind=IdentifierKind.DOCKET,
        value="FSIS-2025-0012",
        span=(11, 25),
        components={"organization": "FSIS", "year": "2025", "sequence": "0012"},
    )
    assert twin in set(candidates)
    assert hash(twin) == hash(candidates[0])
    # Components are compared and hashed by their pairs, not by their order.
    reordered = IdentifierCandidate(
        kind=twin.kind,
        value=twin.value,
        span=twin.span,
        components={"sequence": "0012", "year": "2025", "organization": "FSIS"},
    )
    assert {twin, reordered} == {twin}


# --------------------------------------------------------------------------- #
# Properties: what must hold of every reader, on every input.


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_a_normalizer_never_invents_a_character(text: str) -> None:
    """Property: a normalizer folds and selects; it never adds.

    Folding is one character for one character -- a dash spelling to "-", a
    letter to its uppercase -- so every character of the answer must already
    be in the folded question. The corrector is the one reader allowed to
    break this, and it is fenced by a roster.
    """

    folded = text.translate(DASH_FOLD).upper()
    for answer in (normalize_rin(text), normalize_regsgov_identifier(text), normalize_docket_reference(text)):
        if not answer:
            continue
        assert set(answer) <= set(folded), (text, answer)


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_what_a_source_states_is_reported_unfolded(text: str) -> None:
    """Property: ``docket_reference_as_stated`` reports, it does not normalize.

    It is the one reader that hands back the source's own characters, en
    dashes and lower case included, because its answer is evidence of what
    was written. Everything it can return is therefore the input itself or
    nothing.
    """

    assert docket_reference_as_stated(text) in ("", text.strip())


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_normalization_is_idempotent(text: str) -> None:
    """Property: a normalized value is already normal."""

    for normalizer in (normalize_rin, normalize_regsgov_identifier, normalize_docket_reference):
        once = normalizer(text)
        assert normalizer(once) == once, (normalizer.__name__, text, once)
    stated = docket_reference_as_stated(text)
    assert docket_reference_as_stated(stated) == stated


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_every_span_indexes_the_original_text(text: str) -> None:
    """Property: a span excises exactly the characters that were read.

    Dash folding is one character for one character precisely so this holds
    through it: the value may spell an en dash as "-", but it may not shift.
    """

    for candidate in detect_identifier_shapes(text):
        start, end = candidate.span
        excised = text[start:end]
        assert len(excised) == len(candidate.value)
        assert excised.upper().translate(DASH_FOLD) == candidate.value


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_a_dash_spelling_never_changes_an_answer(text: str) -> None:
    """Property: every dash spelling is the same identifier."""

    en_dashed = text.replace("-", "–")
    assert [c.value for c in detect_identifier_shapes(en_dashed)] == [c.value for c in detect_identifier_shapes(text)]
    assert normalize_rin(en_dashed) == normalize_rin(text)
    assert normalize_regsgov_identifier(en_dashed) == normalize_regsgov_identifier(text)


@pytest.mark.parametrize("seed", range(25))
def test_a_classifier_never_answers_from_bare_digits(seed: int) -> None:
    """Property: no numbering system is ever inferred from digits alone.

    The label is the type declaration. A value with no letter in it declares
    nothing, however it is punctuated.
    """

    rng = random.Random(20260822 + seed)
    digits = "".join(rng.choice("0123456789-  ./#") for _ in range(rng.randrange(1, 24)))
    assert numbering_system(digits) is None, digits
    assert not detect_identifier_shapes(digits) or all(
        c.kind is IdentifierKind.FEDERAL_REGISTER_DOCUMENT for c in detect_identifier_shapes(digits)
    ), digits


# --------------------------------------------------------------------------- #
# The numbering-system classifier.


def test_a_numbering_system_is_read_from_the_label_a_value_states() -> None:
    """A docket column carries fifteen agencies' numbering systems beside
    Regulations.gov dockets. The label is the type declaration, so recording
    which system a value belongs to needs no oracle -- only parsing a
    system's internals would. Measured over the 608,758 distinct references,
    this names the system for 360,879 of them."""

    assert numbering_system("RELEASE NO. 33-8176") is NumberingSystem.RELEASE_NUMBER
    assert numbering_system("FILE NO. S7-08-22") is NumberingSystem.FILE_NUMBER
    assert numbering_system("FRL #10-014") is NumberingSystem.EPA_FEDERAL_REGISTER_LOCATOR
    assert numbering_system("OMB # 0938-0534") is NumberingSystem.OMB_CONTROL_NUMBER
    assert numbering_system("AD 2000-01-01") is NumberingSystem.AIRWORTHINESS_DIRECTIVE
    assert numbering_system("Airspace Dock No. 00-AGL-06") is NumberingSystem.AIRSPACE_DOCKET
    assert numbering_system("Project 0741") is NumberingSystem.PROJECT_NUMBER
    assert numbering_system("Amendment # 1") is NumberingSystem.AMENDMENT_NUMBER
    assert numbering_system("PUBLIC NOTICE #3744") is NumberingSystem.PUBLIC_NOTICE


def test_no_two_numbering_labels_claim_one_value() -> None:
    """The table's order is not load-bearing, and this is why.

    Each label opens on a different word, so at most one can match. Measured
    over the 608,758 distinct docket references: zero values match two. The
    check is here so that adding a tenth label which collides with an
    existing one fails loudly instead of being silently ordered around.
    """

    from spicy_docs.interpretation.identifier_shapes import _NUMBERING_SYSTEM_LABELS

    stated_by_system = {
        NumberingSystem.EPA_FEDERAL_REGISTER_LOCATOR: "FRL #10-014",
        NumberingSystem.OMB_CONTROL_NUMBER: "OMB # 0938-0534",
        NumberingSystem.AIRWORTHINESS_DIRECTIVE: "AD 2000-01-01",
        NumberingSystem.AIRSPACE_DOCKET: "Airspace Dock No. 00-AGL-06",
        NumberingSystem.RELEASE_NUMBER: "RELEASE NO. 33-8176",
        NumberingSystem.FILE_NUMBER: "FILE NO. S7-08-22",
        NumberingSystem.PUBLIC_NOTICE: "PUBLIC NOTICE #3744",
        NumberingSystem.PROJECT_NUMBER: "Project 0741",
        NumberingSystem.AMENDMENT_NUMBER: "Amendment # 1",
    }
    assert set(stated_by_system) == {system for system, _ in _NUMBERING_SYSTEM_LABELS}
    for system, stated in stated_by_system.items():
        claimants = {named for named, label in _NUMBERING_SYSTEM_LABELS if label.match(stated)}
        assert claimants == {system}, stated


def test_a_numbering_label_must_open_the_value() -> None:
    """The label declares the type only when the value leads with it.

    A label found anywhere would make every sentence mentioning a release a
    release number.
    """

    for stated in ("RELEASE NO. 33-8176", "Project 0741", "AD 2000-01-01"):
        assert numbering_system(stated) is not None
        assert numbering_system(f"see {stated}") is None, stated


def test_a_label_with_nothing_behind_it_names_no_system() -> None:
    """Presentation with nothing to present. The rule is the same for every
    system in the table, including the airworthiness directive, whose pattern
    looks past its punctuation to the first digit without consuming it."""

    assert numbering_system("Docket No.") is None
    assert numbering_system("Project") is None
    assert numbering_system("Release No.") is None
    assert numbering_system("AD") is None
    assert numbering_system("AD 2") is NumberingSystem.AIRWORTHINESS_DIRECTIVE
    assert numbering_system("") is None
    assert numbering_system(None) is None


def test_no_numbering_system_is_ever_inferred_from_bare_digits() -> None:
    """A bare number and a bare year-sequence name no numbering system."""
    assert numbering_system("0741") is None
    assert numbering_system("33-8176") is None


def test_a_resolvable_docket_answers_before_any_other_system() -> None:
    """Bare or behind a label, a Regulations.gov docket is the one system this
    registry can resolve, so it answers first."""

    assert numbering_system("EPA-HQ-OAR-2004-0015") is NumberingSystem.REGULATIONS_GOV_DOCKET
    assert numbering_system("DOCKET #: RBS-22-BUSINESS-0021") is NumberingSystem.REGULATIONS_GOV_DOCKET


# --------------------------------------------------------------------------- #
# The corrector: the one reader allowed to change a character.


def test_a_damaged_rin_is_corrected_only_against_a_roster() -> None:
    """Same contract as the Public Law correction: named damage operators,
    a pinned roster as oracle, exactly one survivor. Measured against the
    Unified Agenda's 46,547 RINs, 269 of the 390 distinct values the Federal
    Register's RIN column states and the shape refuses resolve, which is 421
    of their 588 occurrences; the rest are refused, including OMB control
    numbers like 3235-0695 filed in a RIN field.
    ``test_the_corrector_answers_the_real_damaged_population`` runs it over
    that population instead of these four specimens."""

    roster = {"0301-AA00", "1018-BI73", "7100-AF57"}
    assert corrected_rin("O301-AA00", roster) == ("0301-AA00", "unique-roster-existence")
    assert corrected_rin("0301 AA00", roster) == ("0301-AA00", "unique-roster-existence")
    assert corrected_rin("1018-B173", roster) == ("1018-BI73", "unique-roster-existence")
    # A space inside the sequence is the other way a hyphen goes missing.
    assert corrected_rin("7100-AF 57", roster) == ("7100-AF57", "unique-roster-existence")


def test_a_rin_correction_refuses_what_the_roster_does_not_hold() -> None:
    """The roster is the fence. A well-formed RIN nobody minted, an OMB
    control number, and a value already correct all yield nothing: the
    function repairs damage, it does not mint identifiers. 55 distinct
    damaged values reach a well-formed RIN the Unified Agenda does not hold
    -- "0648-X081" reaches "0648-XO81" -- and every one is refused."""

    roster = {"0301-AA00"}
    assert corrected_rin("9999-ZZ99", roster) is None
    assert corrected_rin("3235-0695", roster) is None
    assert corrected_rin("0648-X081", roster) is None
    assert corrected_rin("0301-AA00", roster) is None
    assert corrected_rin("", roster) is None
    assert corrected_rin(None, roster) is None


def test_a_correction_never_applies_two_operators() -> None:
    """One named operator, or nothing. "2050 AEO5" needs both the missing
    hyphen and a homoglyph to reach a well-formed RIN, so it is refused even
    when the destination is in the roster."""

    assert corrected_rin("2050 AEO5", {"2050-AE05"}) is None


def test_a_correction_refuses_rather_than_choosing_between_survivors() -> None:
    """Two roster entries one operator away is an ambiguity, not an answer."""

    assert corrected_rin("0301-AAO0", {"0301-AA00", "0301-AAOO"}) is None


@pytest.mark.parametrize("text", PROPERTY_CORPUS)
def test_a_correction_only_ever_answers_with_a_roster_member(text: str) -> None:
    """Property: the oracle, not the operator, decides what may be returned."""

    roster = {"0301-AA00", "1018-BI73", "7100-AF57", "2060-AV45"}
    answer = corrected_rin(text, roster)
    if answer is None:
        return
    value, evidence = answer
    assert value in roster
    assert evidence == "unique-roster-existence"
    assert normalize_rin(text) is None  # a correct value is never "corrected"


def test_the_closed_segment_vocabulary_admits_only_its_five_tokens() -> None:
    """The trailing token is a closed set of five, and a sixth is not one.

    ``_DOCKET_SEGMENT`` exists because the fence that refuses a docket
    ending on letters was refusing a real docket: the pinned column states
    "Docket #GIPSA-2010-FGIS-0014-NONRULEMAKING" in the publisher's own
    words, and the module's own comment named the same family as a
    malformation. The vocabulary is spelled out rather than generalized to
    ``[A-Za-z]+`` -- generalizing reopens the fence -- so the negative
    fixture here is the whole point of the rule: an invented sixth token
    must NOT be admitted, and the disaster numbers the fence was built for
    must stay refused.
    """

    def one(value: str) -> IdentifierCandidate:
        (candidate,) = [c for c in detect_identifier_shapes(value) if c.value == value]
        return candidate

    # Both slots in one identifier: office between year and docket sequence,
    # segment between docket sequence and document sequence. Nothing else in
    # the corpus exercises the two together.
    both = one("GIPSA-2008-FGIS-0002-NONRULEMAKING-0001")
    assert both.kind is IdentifierKind.REGULATIONS_GOV_DOCUMENT
    assert both.components == {
        "organization": "GIPSA",
        "year": "2008",
        "office": "FGIS",
        "docket_sequence": "0002",
        "segment": "NONRULEMAKING",
        "document_sequence": "0001",
    }

    # The token terminating a docket, with no document sequence after it --
    # the shape the fence used to refuse outright.
    terminal = one("GIPSA-2010-FGIS-0014-NONRULEMAKING")
    assert terminal.kind is IdentifierKind.DOCKET
    assert terminal.components["segment"] == "NONRULEMAKING"

    # DRAFT is the rarest member and the only one that generalizes across
    # agencies: two instances, two agencies, seven years apart. Both are
    # documents, and both used to read as a DOCKET whose "year" was the
    # docket sequence -- two wrong answers on one value, not one.
    for value, organization, year in (
        ("EPA-HQ-OW-2025-0322-DRAFT-29781", "EPA-HQ-OW", "2025"),
        ("FRA-2006-24216-DRAFT-0024", "FRA", "2006"),
    ):
        candidate = one(value)
        assert candidate.kind is IdentifierKind.REGULATIONS_GOV_DOCUMENT
        assert candidate.components["organization"] == organization
        assert candidate.components["year"] == year
        assert candidate.components["segment"] == "DRAFT"

    # THE NEGATIVE FIXTURE. A token outside the five is not a segment, and
    # the value falls back to whatever the grammar said before -- never to a
    # document with an invented segment.
    assert not any("segment" in c.components for c in detect_identifier_shapes("GIPSA-2008-FGIS-0002-WITHDRAWN-0001"))
    # And the fence still does the job it was built for.
    assert detect_identifier_shapes("FEMA-1971-DR") == []
    assert detect_identifier_shapes("Internal Agency Docket No. FEMA-1971-DR") == []


def test_a_ferc_docket_is_not_a_regulations_gov_docket() -> None:
    """FERC runs its own docket registry, and the Federal Register fills
    docket_ids from whatever number the filing agency puts in its heading, so
    both systems arrive in one column. Regulations.gov settles which is which:
    its API answers 400 -- malformed, not merely absent -- for ER00-2089-000
    and AD10-12-017, and 200 for EPA-HQ-OAR-2004-0015 (verified 2026-08-22).
    24,548 distinct references were being reported as Regulations.gov dockets.
    Prefixes are FERC's own published list (Docket Prefix List, June 2025)."""
    for value in ("ER00-2089-000", "AD10-12-017", "CP26-20-000", "RM98-1-000"):
        assert normalize_docket_reference(value) is None, value
        assert numbering_system(value) is NumberingSystem.FERC_DOCKET, value
    assert normalize_docket_reference("EPA-HQ-OAR-2004-0015") == "EPA-HQ-OAR-2004-0015"
    assert normalize_docket_reference("AMS-SC-25-0848") == "AMS-SC-25-0848"


def test_the_two_ad_systems_are_told_apart_by_their_shape() -> None:
    """FERC's AD is administrative; the FAA's AD is an airworthiness directive
    numbered year-biweek-sequence. They share two letters, so the classifier
    reads the whole form rather than the leading letters."""
    assert numbering_system("AD10-12-017") is NumberingSystem.FERC_DOCKET
    assert numbering_system("AD 2000-01-01") is NumberingSystem.AIRWORTHINESS_DIRECTIVE


def test_a_prefix_shared_with_a_real_agency_is_left_alone() -> None:
    """PT is a FERC prefix AND a Regulations.gov agency id, so it is absent
    from the FERC list: refusing it would cost real dockets to exclude
    ambiguous ones, and ambiguity refuses to act."""
    from spicy_docs.interpretation import identifier_shapes as shapes

    assert "PT" not in shapes._FERC_DOCKET_PREFIXES


# --------------------------------------------------------------------------- #
# New in spicy-docs: the unpadded comparison key and the rulemaking docket
# spelling spicy-regs joins on (consolidation item A7, ruling 6).


@pytest.mark.parametrize(
    ("stated", "key"),
    [
        # The two spellings the plan names: Regulations.gov's padded
        # ``fr_doc_num`` against the number the Register issued.
        ("2010-02394", "2010-2394"),
        ("E9-09366", "E9-9366"),
        # Read off the published rule_targets' missing references: a bare
        # legacy number, and an en-dash Regulations.gov typed.
        ("06-00018", "06-18"),
        ("2015\u201307390", "2015-7390"),
        # A sequence that is all zeros keeps one digit rather than vanishing.
        ("2010-00000", "2010-0"),
        # Only the sequence moves: a correction keeps its year, and its key is
        # a fixed point although the correction form's five-digit tail refuses
        # the key as written.
        ("C1-2012-09978", "C1-2012-9978"),
        ("C1-2012-9978", "C1-2012-9978"),
        # A six-digit tail the shape refuses as written, whose key is a legacy
        # number: the one missing reference the survey's rule resolved and the
        # first version of this key did not.
        ("E8-030520", "E8-30520"),
        # Already unpadded, and folded like every other reader here.
        ("2010-2394", "2010-2394"),
        (" e9-09366 ", "E9-9366"),
    ],
)
def test_a_document_number_reduces_to_its_unpadded_key(stated: str, key: str) -> None:
    """The padding is presentation for the comparison, and the key is a fixed point."""
    assert unpadded_federal_register_document_number(stated) == key
    assert unpadded_federal_register_document_number(key) == key


@pytest.mark.parametrize(
    "value",
    [
        "SSA-2010-0037",  # a docket
        "Docket No. SSA-2010-0037",
        "1625-AA00",  # a RIN
        "89 FR 12345",  # a citation, not a number
        "2014-04654s",  # colophon damage the column itself carries
        "2010-1234567",  # no padding of it is a document number
        "",
        None,
    ],
)
def test_only_a_document_number_has_a_key(value: object) -> None:
    """A value no document-number form reads gets no key, so it can never join as one."""
    assert unpadded_federal_register_document_number(value) is None


def test_the_key_is_idempotent_over_every_form_the_module_reads() -> None:
    """Keying a key changes nothing, for a specimen of every document-number production here."""
    specimens = [
        "2012-00019",
        "2010-1",
        "09-19806",
        "00-1",
        "94-120124",
        "E9-654",
        "X10-11220",
        "X09-101207",
        "E3-2013-2261",
        "C1-2012-09978",
        "R1-2010-13257",
        "R1-10679",
    ]
    for specimen in specimens:
        key = unpadded_federal_register_document_number(specimen)
        assert key is not None, specimen
        assert unpadded_federal_register_document_number(key) == key, specimen


def test_the_key_is_compared_on_both_sides_and_refused_where_it_collides() -> None:
    """Why the docstring prescribes the join it does, on the Register's own numbers.

    The Register pads from 2013 on, so unpadding only the reference would
    break an exact match; and two bare-legacy documents published months apart
    share one key, so a key reaching both must be refused. Both specimens are
    real ``document_number`` values in the Register's own column.
    """
    assert unpadded_federal_register_document_number("2016-00263") == "2016-263"
    assert unpadded_federal_register_document_number("2016-263") == "2016-263"
    assert unpadded_federal_register_document_number("94-0190") == unpadded_federal_register_document_number("94-190")


def test_a_labelled_docket_is_read_behind_its_label() -> None:
    """The rulemaking tables' own specimen: the FR docket column states the label."""
    assert normalize_docket_reference("Docket No. SSA-2010-0037") == "SSA-2010-0037"


# --------------------------------------------------------------------------- #
# New in spicy-docs: the one RIN shape a published key may take.


def test_the_published_rin_is_the_narrow_shape_and_folds_like_every_reader() -> None:
    """Four digits, two capitals, two digits; case and dash folded; nothing wider ever a key."""
    assert PUBLISHED_RIN == r"\d{4}-[A-Z]{2}\d{2}"
    assert published_rin("3133-AF97") == "3133-AF97"
    assert published_rin(" 3133\u2013af97 ") == "3133-AF97"
    # The wide detector admits these; a published key never does.
    for damaged in ("1625-AAOO", "2060-XXXX", "0648-XA123", "0648-A110"):
        assert published_rin(damaged) is None, damaged
    assert normalize_rin("1625-AAOO") == "1625-AAOO"
    # A value that merely contains one is not one.
    assert published_rin("RIN 3133-AF97") is None


# --------------------------------------------------------------------------- #
# New in spicy-docs: the column reader takes the prose reader's closed trailing
# tokens. 67 of the retained Regulations.gov documents table's 278,370 distinct
# docket ids end on one, each the publisher's own statement of a document's
# docket, and the column reader refused every one until 2026-09-23.


@pytest.mark.parametrize(
    "docket",
    [
        "GIPSA-2006-FGIS-0029-NONRULE",
        "GIPSA-2006-PSP-0028-RULE",
        "GIPSA-2010-FGIS-0014-NONRULEMAKING",
        "GIPSA-2009-FGIS-0011-RULEMAKING",
    ],
)
def test_a_docket_ending_on_a_segment_token_is_read_as_itself(docket: str) -> None:
    """The column reader and the prose reader now read one convention, written once."""
    assert normalize_docket_reference(docket) == docket
    assert normalize_docket_reference(f"Docket #{docket}") == docket
    assert [c.value for c in detect_identifier_shapes(docket) if c.kind is IdentifierKind.DOCKET] == [docket]


@pytest.mark.parametrize(
    "value",
    [
        "GIPSA-2008-FGIS-0002-WITHDRAWN",  # a sixth token is not one of the five
        "FEMA-1971-DR",  # the fence the digits-last rule exists for
        "Internal Agency Docket No. FEMA-1971-DR",
        "GSA-NA-2005",  # a real docket with no sequence: its silhouette is every such number's
    ],
)
def test_the_segment_admits_only_its_five_tokens_after_a_sequence(value: str) -> None:
    """Only a closed token after a real sequence is admitted; the refused shapes stay refused."""
    assert normalize_docket_reference(value) is None


# --------------------------------------------------------------------------- #
# New in spicy-docs: every docket a docket-column reference names. Specimens
# are real ``fr_docket_links.docket_id`` values from the rulemaking build,
# each naming a docket the Regulations.gov dockets table holds; 5,825 such
# link rows were refused by the single reader.


@pytest.mark.parametrize(
    ("reference", "dockets"),
    [
        # A longer label.
        ("Docket ID No. BOEM-2011-0076", ("BOEM-2011-0076",)),
        ("Docket ID Number: DOT-OST-2026-2707", ("DOT-OST-2026-2707",)),
        ("Docket ID. FMCSA-2009-0154", ("FMCSA-2009-0154",)),
        ("U.S. DOT Docket Number NHTSA-2001-8797", ("NHTSA-2001-8797",)),
        ("Waiver Petition Docket Number FRA-2000-6877", ("FRA-2000-6877",)),
        ("Document Number AMS-FV-09-0022", ("AMS-FV-09-0022",)),
        ("FDMS No. NARA-18-0003", ("NARA-18-0003",)),
        ("No. CPSC-2010-0022", ("CPSC-2010-0022",)),
        ("[Docket No. FAA-2022-1316", ("FAA-2022-1316",)),
        # A note after the docket, whose numbers end the reading.
        ("EPA-HQ-OAR-2002-0086, FRL-8231-8", ("EPA-HQ-OAR-2002-0086",)),
        ("Docket No. FRA-2005-23281, Notice No. 2", ("FRA-2005-23281",)),
        ("Docket No. PHMSA-2012-0257 (HM-258)", ("PHMSA-2012-0257",)),
        ("Docket No. FAA-2007-27723 Directorate Identifier 2007-CE-029-AD", ("FAA-2007-27723",)),
        ("Docket Number CDC-2018-0050, NIOSH-314", ("CDC-2018-0050",)),
        ("Document Number AMS-SC-19-0103, SC-20-326", ("AMS-SC-19-0103",)),
        ("EPA-R06-RCRA-2008-0756-", ("EPA-R06-RCRA-2008-0756",)),
        # A list: every member.
        ("Docket Nos. FDA-2009-E-0202 and FDA-2009-E-0204", ("FDA-2009-E-0202", "FDA-2009-E-0204")),
        ("EPA-HQ-OPP-2013-0654 and EPA-HQ-OPP-2013-0655", ("EPA-HQ-OPP-2013-0654", "EPA-HQ-OPP-2013-0655")),
        (
            "Docket Nos. FAA-2007-0410, FAA-2007-0411, and FAA-2007-0412",
            ("FAA-2007-0410", "FAA-2007-0411", "FAA-2007-0412"),
        ),
        ("and FDA-2015-N-1837", ("FDA-2015-N-1837",)),
        # A whole docket is still the single reader's answer.
        ("GIPSA-2010-FGIS-0014-NONRULEMAKING", ("GIPSA-2010-FGIS-0014-NONRULEMAKING",)),
    ],
)
def test_every_docket_a_reference_names_is_read(reference: str, dockets: tuple[str, ...]) -> None:
    """Labels, notes and lists around a docket are presentation; each docket named is returned, in order."""
    assert normalize_docket_references(reference) == dockets


@pytest.mark.parametrize(
    "reference",
    [
        "File No. SR-Amex-2003-102",  # another system's label: no docket noun, nothing read
        "MM Docket No. 98-213",
        "ER00-2089-000",  # FERC, fenced as the single reader fences it
        "Internal Agency Docket No. FEMA-4319-DR",
        "WO-150-1820-00 1A",  # a serial with a number after it, not a docket with a note
        "FAR Case 2017-014, Docket No. FAR-2017-0014",  # not a search: it must open on a docket
        "see the docket for FDA-2015-N-1837",
        "Docket No.",
        "",
        None,
    ],
)
def test_a_reference_that_does_not_open_on_a_docket_names_none(reference: object) -> None:
    """The reader walks a docket column's value; it does not search prose for anything docket-shaped."""
    assert normalize_docket_references(reference) == ()
