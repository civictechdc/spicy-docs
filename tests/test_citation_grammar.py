"""The single citation grammar, and the two defects the port fixed.

Pins what `spicy_docs.interpretation.citation_grammar` reads by rule rather than by shape: the CFR and
authority families, the fail-closed boundary and range-ordering rules, popular-name capture, and
the corpus-measured repairs, with every corpus count taken over the digest-pinned 797,170-row
Agenda legal-authority table rather than a live build. The two defects pinned here are the
internal-token right-edge omission: "Social Security" offered "Sec" and gave up "urity", and
"6921through" read as section "6921thr".

Ported with the module from RefSpec ``tests/test_citation_grammar.py`` at RefSpec ``4a680c81``: every
test that reads only strings is here unchanged apart from the import path. The fifteen that read RefSpec's
pinned inputs -- the digest-pinned Agenda table, the U.S.C. section oracle, the OLRC popular-name and act
indexes, the CFR subject index, the Public Law/Statutes oracle and the built timetable table -- stay in RefSpec
beside those inputs, together with the corpus half of ``test_a_normalized_name_is_a_fixed_point``, and run
against this module once RefSpec imports it back. The "pinned Agenda table" the counts below cite is that
RefSpec table, not an input of this repository."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from spicy_docs.interpretation import citation_grammar
from spicy_docs.interpretation.citation_grammar import (
    CfrCitationRange,
    find_act_relative_citations,
    normalize_popular_name,
    parse_authority_citation,
    parse_cfr_citations,
    parse_eo_compilation_locators,
    parse_federal_register_citations,
    parse_supreme_court_citation,
    stated_act_name,
    usc_section_pinpoint,
    usc_token_is_chapter_qualified,
)


def _parts(text: str, **kwargs) -> list[str | None]:
    """The cfr_part of each parsed CFR citation, for compact assertions."""

    return [citation.cfr_part for citation in parse_cfr_citations(text, **kwargs)]


def test_a_lettered_part_is_not_merged_into_its_numeric_neighbour() -> None:
    """Both ancestor grammars capture (?P<part>\\d+), so "7 CFR 15a" read as 15.

    That is not a rounding error: the OFR's index lists 7 CFR 15 and 7 CFR 15a
    as separate parts, so merging them unions two distinct bodies of regulation.
    """

    assert _parts("7 CFR 15a") == ["15a"]
    assert _parts("42 CFR 59a") == ["59a"]
    assert _parts("7 CFR 15") == ["15"]


def test_a_rule_number_never_becomes_a_part() -> None:
    """17 CFR 15c3-3 is a rule under part 240; "15c" is not a part."""

    assert _parts("17 CFR 15c3-3") == [None]
    assert _parts("17 CFR 12d1-1") == [None]


def test_list_expansion_is_a_declared_policy_not_a_default() -> None:
    """Prose and a structured field need opposite answers.

    In the Unified Agenda's CFR field, 953 references list parts with no label
    at all against 43 with a plural label -- so the prose-safe rule drops the
    dominant shape. In a sentence, the same rule stops "part 37" from
    swallowing the next number it sees.
    """

    unlabelled = "40 CFR 60, 61, 63"
    assert _parts(unlabelled) == ["60"]
    assert _parts(unlabelled, list_expansion="always") == ["60", "61", "63"]
    # A plural label licenses expansion under either policy.
    assert _parts("17 CFR parts 37, 38, 39") == ["37", "38", "39"]
    with pytest.raises(ValueError, match="unknown list expansion"):
        parse_cfr_citations("40 CFR 60", list_expansion="sometimes")


def test_an_impossible_title_is_returned_rather_than_dropped() -> None:
    """Both ancestors drop it, which makes a data-quality question unanswerable."""

    reserved = parse_cfr_citations("35 CFR ch. II")
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in reserved] == [(35, None, True)]
    out_of_range = parse_cfr_citations("234 CFR 100")
    assert out_of_range[0].title_is_possible is False
    assert out_of_range[0].cfr_part == "100"


def test_part_length_asserts_nothing_below_six_digits() -> None:
    """5 CFR 10001 is real (National Council on Disability), so five digits
    proves nothing either way; the evidence signal is OFR-index membership,
    carried as a column in the Agenda tables. Six digits and up stays
    asserted damage."""

    assert parse_cfr_citations("5 CFR 10001")[0].part_is_plausible is True
    assert parse_cfr_citations("40 CFR 60758")[0].part_is_plausible is True  # unknowable by length
    assert parse_cfr_citations("42 CFR 412106")[0].part_is_plausible is False
    assert parse_cfr_citations("48 CFR 9904")[0].part_is_plausible is True


def test_the_boundary_guard_survives_the_port() -> None:
    """The guard blocks OFFSET matching; it does not reject zero-padding.

    The ancestor's hazard was "040 CFR 060" matching at offset 1 as a
    fabricated "40 CFR". The guard alone prevents that: a title may not begin
    mid-token. Whole-token zero-padding is a different thing -- the Agenda
    carries 95 zero-padded titles ("07 CFR 1943" is USDA's title 7) -- and is
    read by its integer value rather than refused.
    """

    # Mid-token: blocked entirely, not read as "40 CFR 60".
    assert parse_cfr_citations("x40 CFR 60") == ()
    # Whole-token zero-padding: read, and the verdict falls on the int.
    padded = parse_cfr_citations("040 CFR 060")
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in padded] == [(40, "60", True)]
    # A zero title is read and judged, not refused. The example used to be
    # "00 CFR 00", which is now a placeholder in its entirety and locates
    # nothing -- a zero title beside a REAL part is what this line is for.
    assert parse_cfr_citations("00 CFR 60")[0].title_is_possible is False


def test_zero_padded_titles_are_read_and_literal_zero_is_labelled() -> None:
    r"""[1-9]\d* lost 61 valid USDA citations and unlabelled 36 damage rows at once."""

    assert parse_cfr_citations("07 CFR 1943")[0].cfr_title == 7
    assert parse_cfr_citations("07 CFR 1943")[0].title_is_possible is True
    zero = parse_cfr_citations("0 CFR 150 to 189")[0]
    assert isinstance(zero, CfrCitationRange)
    assert (zero.start.cfr_title, zero.start.title_is_possible, zero.end.title_is_possible) == (0, False, False)


def test_the_part_is_a_join_key_so_leading_zeros_normalize() -> None:
    """ "0718" and "718" are one part; the written form survives in the source text."""

    assert parse_cfr_citations("7 CFR 0718")[0].cfr_part == "718"
    # An all-zero part still normalizes to "0". The example moved off
    # "00 CFR 00" because that whole value is now read as a placeholder; the
    # zeros being normalized are the part's, and a real title carries them
    # just as well.
    assert parse_cfr_citations("40 CFR 00")[0].cfr_part == "0"


def test_sections_are_read_not_discarded() -> None:
    """A section after § is read into cfr_section, and a trailing sentence period is not part of it."""

    citation = parse_cfr_citations("45 C.F.R. § 302.32(b)")[0]
    assert (citation.cfr_part, citation.cfr_section) == ("302", "32")
    # A trailing period belongs to the sentence, not the section name.
    assert parse_cfr_citations("49 CFR 900.42.")[0].cfr_section == "42"


def test_every_authority_shape_the_agenda_carries() -> None:
    """Pins the Agenda's authority shapes -- U.S.C., public law, executive order, Statutes at Large -- as typed rows."""

    assert [a.authority_type for a in parse_authority_citation("5 U.S.C. 301")] == ["usc"]
    assert parse_authority_citation("PL 107-171")[0].public_law == "107-171"
    assert parse_authority_citation("E.O. 13559")[0].executive_order == "13559"
    assert parse_authority_citation("106 Stat. 4777")[0].statute_volume == 106
    both = parse_authority_citation("5 U.S.C. 301; PL 95-91")
    assert {a.authority_type for a in both} == {"usc", "public_law"}


# --------------------------------------------------------------------------- #
# Lessons carried from the ancestor implementations, each pinned by the case
# that bought it.


def test_the_usc_range_ordering_rule_is_fail_closed() -> None:
    """A hyphen means two things in the U.S. Code; ordering decides which.

    "1395w-4" is one section's name (its suffix is a small ordinal);
    "7401-7671q" is a range (its second endpoint sorts after its first). A
    pair that satisfies neither reading honestly — "4801-4582", "7671-7671",
    "80a-06" — stays one opaque token, because reading it either way would be
    an invention.

    The abbreviated "1484-86" was in that company until an oracle settled it;
    see :func:`test_an_abbreviated_span_is_two_sections_not_one_name`.
    """

    ranged = parse_authority_citation("42 U.S.C. 7401-7671q")[0]
    assert (ranged.usc_section, ranged.usc_section_end) == ("7401", "7671q")
    spelled = parse_authority_citation("42 U.S.C. 7401 to 7671q")[0]
    assert (spelled.usc_section, spelled.usc_section_end) == ("7401", "7671q")
    compound = parse_authority_citation("12 U.S.C. 1831p-1")[0]
    assert (compound.usc_section, compound.usc_section_end) == ("1831p-1", None)
    assert compound.parse_status == "ok"
    for text in ("50 U.S.C. 4801-4582", "42 U.S.C. 7671-7671", "15 USC 80a-06"):
        declined = parse_authority_citation(text)[0]
        assert declined.usc_section_end is None, text


def test_usc_chapters_are_typed_rows_not_failures() -> None:
    """Bought as the largest slice of the citation bakeoff's shared-miss cell.

    citations.py kept chapters out of its authority parse; the Agenda cites
    4,377 of them, so here they are typed rather than 'other'/'failed'.
    """

    chapter = parse_authority_citation("49 U.S.C. ch. 311")[0]
    assert (chapter.authority_type, chapter.usc_chapter) == ("usc_chapter", "311")
    # "22 USC Ch. 34- The Peace Corps Act": the dash is punctuation before a
    # title, not a range separator, because no number follows it.
    named = parse_authority_citation("22 USC Ch. 34- The Peace Corps Act")[0]
    assert (named.usc_chapter, named.usc_chapter_end) == ("34", None)
    assert named.parse_status == "partial"


def test_a_section_list_expands_under_its_title_and_stops_at_citations() -> None:
    """A USC section list expands under its title, and a number leading another citation is never a list member."""

    listed = parse_authority_citation("42 U.S.C. 1395, 1396, 1397")
    assert [c.usc_section for c in listed] == ["1395", "1396", "1397"]
    assert {c.parse_status for c in listed} == {"partial"}
    # A number that leads another citation form is never a list member.
    mixed = parse_authority_citation("5 U.S.C. 301, 117 Stat. 429")
    assert [(c.authority_type, c.usc_section or c.statute_page) for c in mixed] == [
        ("usc", "301"),
        ("statute_at_large", 429),
    ]


def test_the_title_form_is_the_spelling_statutes_themselves_use() -> None:
    """Pins "section X of title T" and its plural list form as the spelling the statutes themselves use."""

    single = parse_authority_citation("section 553 of title 5")[0]
    assert (single.usc_title, single.usc_section, single.parse_status) == (5, "553", "ok")
    plural = parse_authority_citation("sections 3501, 3502 and 3503 of title 44")
    assert [c.usc_section for c in plural] == ["3501", "3502", "3503"]


def test_a_named_code_supplies_its_own_title() -> None:
    """ "I.R.C. 337(d)" and "26 U.S.C. 337(d)" must reach one identifier."""

    irc = parse_authority_citation("I.R.C. 337(d)")[0]
    assert (irc.authority_type, irc.usc_title, irc.usc_section) == ("usc", 26, "337")


def test_the_code_names_itself_three_ways() -> None:
    """Pins "U.S. Code", "U.S.C.", and the annotated "U.S.C.A." as the same title-and-section read."""

    assert parse_authority_citation("49 U.S. Code 106")[0].usc_section == "106"
    annotated = parse_authority_citation("50 U.S.C.A. 4701(a)")[0]
    assert (annotated.usc_title, annotated.usc_section) == (50, "4701")


def test_parse_status_distinguishes_covered_from_embedded() -> None:
    """ok for covered text with ignorable tails and partial when a subsection is stripped; failed
    text is retained, never dropped.
    """

    assert parse_authority_citation("5 U.S.C. 301")[0].parse_status == "ok"
    # "et seq." and "as amended" are ignorable tails, not extra prose.
    assert parse_authority_citation("5 U.S.C. 301 et seq.")[0].parse_status == "ok"
    assert parse_authority_citation("42 U.S.C. 2000bb as amended")[0].parse_status == "ok"
    # A stripped subsection is uncovered text: their own worked example.
    assert parse_authority_citation("42 USC 9608 (b)")[0].parse_status == "partial"
    # Unreadable text is retained, never dropped.
    failed = parse_authority_citation("the Commissioner's general authority")[0]
    assert (failed.authority_type, failed.parse_status) == ("other", "failed")


def test_capitalization_is_evidence_for_bare_abbreviations() -> None:
    """Prose contains "eo" and "stat" as word fragments; labels relax the rule."""

    assert parse_authority_citation("Romeo 12345")[0].authority_type == "other"
    assert parse_authority_citation("eo 13559")[0].authority_type == "other"
    assert parse_authority_citation("E.O. 13559")[0].executive_order == "13559"
    assert parse_authority_citation("EO 13559")[0].executive_order == "13559"
    # The spelled form may relax case and accepts early two-digit orders.
    assert parse_authority_citation("Executive Order 11")[0].executive_order == "11"
    assert parse_authority_citation("77 Stat. 392")[0].statute_page == 392


def test_a_compilation_locator_is_never_a_cfr_citation() -> None:
    """ "3 CFR, 1977 Comp., p. 123" is the page an EO was printed on.

    Left in the CFR grammar it parses as title 3, part 1977 — plausible on
    every axis and entirely fabricated. The closed separator set was bought
    when an enumerated one left "through" still minting urn:rkaf:us:cfr:3:1949.
    """

    assert parse_cfr_citations("3 CFR, 1977 Comp., p. 123") == ()
    assert parse_cfr_citations("3 CFR 1949 through 1953 Comp") == ()
    locator = parse_eo_compilation_locators("3 CFR, 1977 Comp., p. 123")[0]
    assert (locator.compilation_start, locator.page) == ("1977", "123")
    # A real title-3 citation still parses.
    assert parse_cfr_citations("3 CFR part 100")[0].cfr_part == "100"


def test_the_title_part_spelling_requires_an_anchor() -> None:
    """The ancestor made both anchors optional; "5, part 2" fabricated a citation."""

    assert [(c.cfr_title, c.cfr_part) for c in parse_cfr_citations("title 40, part 60")] == [(40, "60")]
    assert parse_cfr_citations("5, part 2 of the plan") == ()


def test_a_cfr_list_never_swallows_the_next_citations_number() -> None:
    """With list expansion on, a CFR list stops before a following citation rather than swallowing its number."""

    mixed = parse_cfr_citations("17 CFR 240, 15 U.S.C. 78c", list_expansion="always")
    assert [(c.cfr_title, c.cfr_part) for c in mixed] == [(17, "240")]


def test_double_letter_sections_are_one_token() -> None:
    """The ancestors' single-letter capture read "2000bb" as 2000b + stray b."""

    rfra = parse_authority_citation("42 U.S.C. 2000bb")[0]
    assert (rfra.usc_section, rfra.parse_status) == ("2000bb", "ok")
    assert parse_authority_citation("42 U.S.C. 300aa-25")[0].usc_section == "300aa-25"


def test_the_recovered_authority_classes_from_the_malformed_census() -> None:
    """Five classes recovered from 39,856 failed rows; each pinned by its case."""

    appendix = parse_authority_citation("50 USC app 2401 et seq")[0]
    assert (appendix.authority_type, appendix.usc_appendix, appendix.usc_section) == ("usc", True, "2401")
    # One row, and it is the appendix one: "50 U.S.C. app. 2401" is NOT also
    # plain 50 U.S.C. 2401, which is a different place. See
    # test_the_appendix_fence_and_the_reason_it_never_has_to_fire for what
    # keeps the plain reader off it.
    only = parse_authority_citation("50 U.S.C. app. 2401")
    assert len(only) == 1
    assert only[0].usc_appendix is True

    plural = parse_authority_citation("Executive Orders 13990 and 14008")
    assert [c.executive_order for c in plural] == ["13990", "14008"]

    plan = parse_authority_citation("Reorganization Plan No. 3 of 1970")[0]
    assert (plan.authority_type, plan.reorganization_plan) == ("reorganization_plan", "3-of-1970")

    wrong_column = parse_authority_citation("delegation of authority at 49 CFR 1.95")[0]
    assert (wrong_column.authority_type, wrong_column.cfr_title, wrong_column.cfr_part) == ("cfr", 49, "1")

    for placeholder in ("Not Yet Determined", "...", "None", "TBD"):
        assert parse_authority_citation(placeholder)[0].authority_type == "unstated"
    # Genuinely unreadable text still says failed/other, never unstated.
    assert parse_authority_citation("MNOPF Trustees, Ltd v United States")[0].authority_type == "other"

    # A case-reporter citation is its own family: it locates a decision.
    case = parse_authority_citation("123 F 3d 1460 (Fed Cir 1997)")[0]
    assert (case.authority_type, case.case_volume, case.case_page) == ("case_citation", 123, 1460)
    # "U.S.C." never reads as the U.S. reporter — the C intervenes.
    assert parse_authority_citation("5 U.S.C. 301")[0].authority_type == "usc"


# --------------------------------------------------------------------------- #
# Authority families added by the residue clustering of 2026-08-21, each
# licensed by a verified source (see research/authority-families-2026-08-21.md).


def test_proclamations_are_numbered_and_memoranda_are_not() -> None:
    """The proclamation series ran past 11037 by mid-2026; memoranda and
    continuation notices are date-identified, so they carry a kind alone."""

    proc = parse_authority_citation("Presidential Proclamation No. 7383 (December 1, 2000)")[0]
    assert (proc.authority_type, proc.presidential_doc_kind, proc.proclamation) == (
        "presidential_document",
        "proclamation",
        "7383",
    )
    assert parse_authority_citation("Proc 10414, 87 FR 35067")[0].proclamation == "10414"
    memo = parse_authority_citation("Presidential Memorandum of January 31, 2014")[0]
    assert (memo.presidential_doc_kind, memo.proclamation) == ("memorandum", None)
    notice = parse_authority_citation("Notice of August 3, 2000 (65 FR 48347)")[0]
    assert notice.presidential_doc_kind == "notice"
    # Lowercase "proc" and a bare "notice of default" are prose, not documents.
    assert parse_authority_citation("proc of default")[0].authority_type == "other"


def test_administrative_orders_are_a_department_heads_own_instrument() -> None:
    """DHS Delegation 0170.1 is cited as legal authority in Federal Register
    rulemakings, which licenses the family; the number shapes are the
    observed set — dotted and dashed. A parenthesized number behind one is a
    PARAGRAPH of the instrument, not a revision of it; see
    :func:`test_a_delegations_paragraph_is_not_a_second_delegation`."""

    order = parse_authority_citation("Secretary's Order No. 3-2007, 72 FR 15907")[0]
    assert (order.authority_type, order.admin_order_number) == ("administrative_order", "3-2007")
    delegation = parse_authority_citation("DHS Delegation No. 0170.1(75)")[0]
    assert delegation.admin_order_number == "0170.1"
    doo = parse_authority_citation("Department of Commerce Department Organization Order 10-4")[0]
    assert doo.admin_order_number == "10-4"
    # "delegation of authority at 49 CFR 1.95" carries no order number and
    # reads as the CFR citation it contains, never as an instrument.
    kinds = {c.authority_type for c in parse_authority_citation("delegation of authority at 49 CFR 1.95")}
    assert "administrative_order" not in kinds


def test_treaty_series_follow_the_bluebook_preference_list() -> None:
    """Pins UST and the S. Treaty Doc. plus UNTS combination as treaty rows in Bluebook preference order."""

    ust = parse_authority_citation("27 UST 1087")[0]
    assert (ust.authority_type, ust.treaty_series, ust.treaty_volume, ust.treaty_page) == (
        "treaty",
        "UST",
        27,
        1087,
    )
    combo = parse_authority_citation("S Treaty Doc 105-51 (1998), 1870 UNTS 167")
    assert {(c.treaty_series, c.treaty_number or c.treaty_volume) for c in combo} == {
        ("S. Treaty Doc.", "105-51"),
        ("UNTS", 1870),
    }


def test_the_constitution_family_reads_articles_and_repairs_a_head_insertion_typo() -> None:
    """Reads an Article/Section citation as the constitution family and repairs a one-insertion
    "Cost" only at the value's head.
    """

    clause = parse_authority_citation("U.S. Const., Art. II, Sec. 2")[0]
    assert (clause.authority_type, clause.constitution_article, clause.constitution_section) == (
        "constitution",
        "II",
        "2",
    )
    # Wave 3 refused "US Cost, Art II, sec 2" as "a guess about which word was
    # meant". Wave 5 overturns that on the value's own structure, not on the
    # word: "Cost" is one insertion from "Const" and from no other label this
    # grammar knows (the two-substitution "Code" has no Article II), and the
    # repair is anchored to the whole value's head AND to the article-section
    # shape only the Constitution has. Measured inert over the 41,378 distinct
    # authority values that already read.
    repaired = parse_authority_citation("US Cost, Art II, sec 2")[0]
    assert (repaired.authority_type, repaired.constitution_article) == ("constitution", "II")
    # The anchor is what makes it a rule: "Cost" anywhere else stays prose.
    assert parse_authority_citation("US Cost of Living Council")[0].authority_type == "other"
    assert parse_authority_citation("Cost, Art II, sec 2")[0].authority_type == "other"


def test_a_compilation_locator_cited_as_authority_is_typed_not_failed() -> None:
    """A compilation locator cited as legal authority is typed as eo_compilation, not failed."""

    row = parse_authority_citation("3 CFR, 1949 to 1953 Comp, p 1002")[0]
    assert (row.authority_type, row.eo_compilation_start, row.eo_compilation_page) == (
        "eo_compilation",
        "1949",
        "1002",
    )


def test_a_statutory_note_is_a_place_the_way_an_appendix_is() -> None:
    """LLSDC, "The Authority of Statutes Placed in Section Notes": the note
    under a section is law. "1252 note" is covered and flagged, not left as
    an uncovered tail."""

    note = parse_authority_citation("8 U.S.C. 1252 note")[0]
    assert (note.usc_section, note.usc_note, note.parse_status) == ("1252", True, "ok")
    plain = parse_authority_citation("8 U.S.C. 1252")[0]
    assert plain.usc_note is False


def test_a_subsection_no_longer_severs_an_act_from_its_name() -> None:
    """ "Sec 1886(d) of the Social Security Act" failed because the
    parenthetical sat between the section and "of the"."""

    names = {normalize_popular_name("Social Security Act")}
    found = find_act_relative_citations("Sec 1886(d) of the Social Security Act", act_names=names)
    assert [(c.act_key, c.section) for c in found] == [("social security act", "1886")]
    # Chained subsections skip too.
    chained = find_act_relative_citations("sec 8a(5)(B) of the Social Security Act", act_names=names)
    assert chained and chained[0].section == "8a"


def test_the_residue_exposed_four_more_recoverable_gaps() -> None:
    """Found by re-clustering the post-families failure pool."""

    # The CFR zero-padding lesson, finally applied to the U.S. Code.
    padded = parse_authority_citation("07 USC 5602")[0]
    assert (padded.usc_title, padded.usc_section) == (7, "5602")
    # The appendix marker appears on either side of the code name.
    inverted = parse_authority_citation("50 app USC 2071")[0]
    assert (inverted.usc_appendix, inverted.usc_section) == (True, "2071")
    # OMB's instrument series, cited as legal authority 408 times.
    circular = parse_authority_citation("OMB Circular A-183")[0]
    assert (circular.admin_order_kind, circular.admin_order_number) == ("OMB Circular", "A-183")
    memo = parse_authority_citation("OMB Memorandum M-20-20")[0]
    assert memo.admin_order_kind == "OMB Memorandum"
    # The Code names itself longhand.
    longhand = parse_cfr_citations("title 40, Code of Federal Regulations, part 60")
    assert [(c.cfr_title, c.cfr_part) for c in longhand] == [(40, "60")]


# --------------------------------------------------------------------------- #
# The 2026-08-21 continuation: residue anatomy of the 9,280 still-failed rows.


def _one(text: str):
    """Parse exactly one authority row, failing loudly on any other count."""

    rows = parse_authority_citation(text)
    assert len(rows) == 1, rows
    return rows[0]


def test_cp1252_dash_mojibake_reads_by_declared_convention() -> None:
    """U+0096/U+0097 are Windows-1252 en/em dashes surviving a bad decode.

    104 authority values carry them ("PL 105\\x96261" is the FY1999 NDAA);
    the bytes appear in no other Agenda field, so the dash table absorbs
    them one-for-one and spans still index the original text.
    """

    assert _one("PL 105\x96261").public_law == "105-261"
    assert _one("PL 110\x97314, sec 104").public_law == "110-314"
    # An en dash and a hyphen side by side is one separator typed twice.
    assert _one("PL 105-\x96261").public_law == "105-261"
    assert _one("Pub. L. 105\x96-261").public_law == "105-261"


def test_a_quoted_placeholder_is_still_a_placeholder() -> None:
    """The Agenda writes '"Not Yet Determined"' with literal quotes 30 times,
    and "Not applicable" 40; both state nothing."""

    assert _one('"Not Yet Determined"').authority_type == "unstated"
    assert _one("Not applicable").authority_type == "unstated"
    assert _one("not applicable").authority_type == "unstated"


def test_a_federal_register_citation_in_the_authority_field_is_typed() -> None:
    """A document locator in the wrong column, the same posture as the CFR
    family: typed as what it is, always partial."""

    row = _one("44 FR 56673")
    assert (row.authority_type, row.parse_status) == ("federal_register", "partial")
    assert (row.fr_volume, row.fr_page) == (44, 56673)
    # Companion citations beside an order both survive.
    rows = parse_authority_citation("30 FR 12319, as amended by EO 11375")
    kinds = {r.authority_type for r in rows}
    assert kinds == {"federal_register", "executive_order"}


def test_revised_statutes_are_their_own_namespace() -> None:
    """R.S. 161 IS 5 U.S.C. 301 (the housekeeping statute), which is why the
    corpus writes them side by side -- and why the R.S. section must never be
    stored in a U.S.C. column."""

    row = _one("RS 463")
    assert (row.authority_type, row.revised_statute_section) == ("revised_statute", "463")
    assert row.usc_title is None
    assert _one("R.S. 2450, as amended").parse_status == "ok"
    rows = parse_authority_citation("R.S. 161, 5 U.S.C. 301")
    assert {r.authority_type for r in rows} == {"revised_statute", "usc"}
    # lowercase is prose, and _LEFT keeps "IRS" whole
    assert _one("rs 463").authority_type == "other"
    assert _one("IRS 463").authority_type == "other"


def test_dc_code_reads_both_spellings_to_one_compound() -> None:
    """ "D.C. Code 24-131" and the older "26 DC Code 102" are one scheme:
    title-section. The inverted read follows the inverted-appendix precedent."""

    assert _one("DC Code 24-131(a)(1)").dc_code_section == "24-131"
    assert _one("26 DC Code 102").dc_code_section == "26-102"
    assert _one("DC Code sec 24-403.01(d-1)(1)").dc_code_section == "24-403.01"
    rows = parse_authority_citation("D.C. Code secs. 24-132(b) and 24-133(b)(2)")
    assert [r.dc_code_section for r in rows] == ["24-132", "24-133"]
    # Naming the Code without a readable section still types the row.
    bare = _one("26 DC Code")
    assert (bare.authority_type, bare.dc_code_section, bare.parse_status) == ("dc_code", None, "partial")


def test_a_bare_title_names_a_body_of_law_not_a_provision() -> None:
    """ "3 CFR" and "16 USC et seq" cite a title wholesale: typed with the
    title, partial -- never "ok" -- and only ever as a whole-value fallback."""

    row = _one("3 CFR")
    assert (row.authority_type, row.cfr_title, row.cfr_part) == ("cfr", 3, None)
    assert _one("48 CFR ch 1").cfr_title == 48
    usc = _one("16 USC et seq")
    assert (usc.authority_type, usc.usc_title, usc.parse_status) == ("usc", 16, "partial")
    assert _one("28 U.S.C.").usc_title == 28
    # Embedded in prose the fallback never fires.
    assert _one("regulations under 16 USC generally").authority_type == "other"


def test_a_stray_period_after_the_title_is_tolerated() -> None:
    """ "15. U.S.C. 78w(a)" -- the dot is the publisher's, the title is 15."""

    row = _one("15. U.S.C. 78w(a)")
    assert (row.usc_title, row.usc_section) == (15, "78w")


def test_a_dot_in_the_public_law_separator_slot_is_the_dashs_damage() -> None:
    """No Public Law citation form is decimal, so "Pub. L 103.311" reads as
    103-311; the CFR-shaped "205.600-205.607" stays refused because the
    dotted range proves the dot is not a separator."""

    assert _one("Pub. L 103.311").public_law == "103-311"
    rows = parse_authority_citation("PL 104.104, 202(h)")
    assert rows[0].public_law == "104-104"
    assert _one("Pub. L. 205.600-205.607").authority_type == "other"


def test_presidential_directives_are_typed_by_kind_like_memoranda() -> None:
    """HSPD directives are typed by kind, and a bare lowercase token stays prose."""

    row = _one("Homeland Security Presidential Directive 12")
    assert (row.authority_type, row.presidential_doc_kind) == (
        "presidential_document",
        "directive",
    )
    assert _one("HSPD-12").presidential_doc_kind == "directive"
    assert _one("hspd-12").authority_type == "other", "bare tokens demand uppercase"


def test_the_secretarys_order_names_its_office() -> None:
    """ "Secretary of Labor's Order 1-2011" (130 rows) with the office named,
    possessive or not, curly or straight apostrophe; its companion FR
    citations become federal_register rows."""

    rows = parse_authority_citation(
        "Secretary of Labor's Order No. 12-71 (36 FR 8754), 8-76 (41 FR 25059), or 9-83 (48 FR 35736), as applicable"
    )
    order = next(r for r in rows if r.authority_type == "administrative_order")
    assert order.admin_order_kind == "Secretary of Labor's Order"
    assert order.admin_order_number == "12-71"
    assert [r.fr_page for r in rows if r.authority_type == "federal_register"] == [
        8754,
        25059,
        35736,
    ]
    curly = parse_authority_citation("Secretary of Labor’s Order 1-2011, 77 FR 1088")
    assert any(r.admin_order_kind == "Secretary of Labor's Order" for r in curly)
    air = _one("Secretary of the Air Force Order 111.1")
    assert air.admin_order_kind == "Secretary of the Air Force Order"
    # A space after the number's dash is tolerated and stripped on capture.
    spaced = parse_authority_citation("Secretary of Labor's Order No. 1- 87, April 21,1987")
    assert any(r.admin_order_number == "1-87" for r in spaced)


def test_a_year_range_licenses_a_comp_less_compilation_locator() -> None:
    """No CFR part is ever "1966-1970", so the range diverts without the word
    "Comp." -- before this, "3 CFR 1971 to 1975" minted a fabricated part
    1971. A single Comp-less year could name a part and stays undiverted."""

    row = _one("3 CFR, 1966\x961970, p 939")
    assert (row.authority_type, row.eo_compilation_start) == ("eo_compilation", "1966")
    assert row.eo_compilation_page == "939"
    assert _one("3 CFR 1971 to 1975").authority_type == "eo_compilation"
    assert _one("3 CFR 1966--1970 p 939").authority_type == "eo_compilation"
    assert parse_cfr_citations("3 CFR 1971 to 1975") == ()
    # The single year stays a CFR read: choosing would be a guess.
    single = parse_cfr_citations("3 CFR 1990")
    assert single and single[0].cfr_part == "1990"


def test_a_mapping_container_publishes_canonical_act_keys() -> None:
    """A spelling-variant index maps "Motor Carrier Act of 1935" to the
    OLRC's own "Motor Carrier Act, 1935"; the key published is always the
    canonical one, so act_resolution's join never sees a variant."""

    lookup = {
        "motor carrier act, 1935": "motor carrier act, 1935",
        "motor carrier act of 1935": "motor carrier act, 1935",
    }
    found = find_act_relative_citations("sec. 204 of the Motor Carrier Act of 1935", act_names=lookup)
    assert [c.act_key for c in found] == ["motor carrier act, 1935"]
    plain = find_act_relative_citations(
        "sec. 204 of the Motor Carrier Act of 1935",
        act_names={"motor carrier act of 1935"},
    )
    assert [c.act_key for c in plain] == ["motor carrier act of 1935"]


# --------------------------------------------------------------------------- #
# The 2026-08-22 third pass: label damage, lettered pages, new instruments.


def test_the_transposed_code_label_reads_uppercase_only() -> None:
    """ "21 UCS 374" is 21 U.S.C. 374 — adjacent transposition, the named
    operator the corroborated corrections already use, reachable from no
    other citation label. Lowercase is prose and stays refused."""

    row = _one("21 UCS 374")
    assert (row.authority_type, row.usc_title, row.usc_section) == ("usc", 21, "374")
    assert _one("21 ucs 374").authority_type == "other"


def test_the_executive_order_label_tolerates_its_two_damages() -> None:
    """ "EO. 14221" carries a stray period; "E0 12250" a zero for its O — one
    keystroke from "EO" and from no other label. The uppercase evidence
    stays required: "Romeo 12345" and "e0 12250" read nothing."""

    assert _one("EO. 14221").executive_order == "14221"
    assert _one("E0 12250").executive_order == "12250"
    assert _one("Romeo 12345").authority_type == "other"
    assert _one("e0 12250").authority_type == "other"


def test_the_stat_label_reads_through_its_measured_damages() -> None:
    """Fused separators ("92 Stat.1660", "61Stat 1180"), the longhand
    "Statute", the dropped-letter "Statue", and the page fused to its own
    "as amended" tail.

    Lowercase "stat" is prose INSIDE a sentence and a citation when it is the
    whole value. Wave 3 pinned the first half of that and asserted the
    second; wave 4 measured it — 38 rows over 16 spellings whose entire value
    is "126 stat 11" or "61 stat. 1180", every volume and page in series and
    cited elsewhere in the same corpus with the capital — so the whole-value
    repair reads them and the in-prose refusal stands unchanged."""

    for text, volume, page in [
        ("sec. 2(a), 92 Stat.1660", 92, 1660),
        ("Articles 12 and 29 of 61 Statue 1180", 61, 1180),
        ("(61Stat 1180)", 61, 1180),
        ("63 Stat 390as amended", 63, 390),
        ("126 stat 11", 126, 11),
        ("61 stat. 1180", 61, 1180),
    ]:
        row = next(r for r in parse_authority_citation(text) if r.authority_type == "statute_at_large")
        assert (row.statute_volume, row.statute_page) == (volume, page), text
    assert _one("the stat 11 report").authority_type == "other"
    assert _one("no more than 5 stat 3 of them").authority_type == "other"


def test_a_lettered_stat_page_keeps_its_identity_in_the_text_column() -> None:
    """ "113 Stat. 1501A-293" pages an appendix; the identity is the lettered
    compound, which the int column cannot state without truncating or
    minting — so the int stays NULL and the compound lives in
    statute_page_text. The comma spelling reads to the same page.

    A range tail is carried in the same column as a range string, and what
    that fixed is pinned in
    :func:`test_a_lettered_statutes_range_carries_its_end_leaf`."""

    row = _one("113 Stat. 1501A-293")
    assert row.authority_type == "statute_at_large"
    assert (row.statute_volume, row.statute_page, row.statute_page_text) == (113, None, "1501A-293")
    assert row.parse_status == "ok"
    comma = _one("114 Stat. 2763A, 326 to 328")
    assert comma.statute_page_text == "2763A-326 to 2763A-328"
    assert comma.parse_status == "ok", "both endpoints are carried, so the value is covered"
    assert _one("114 Stat 2763a-326 to -328").statute_page_text == "2763A-326 to 2763A-328"


def test_a_compilation_fragment_reads_whole_value_only() -> None:
    """ "1991 Comp p 351" lost its "3 CFR" head; only Title 3 prints Comp.
    pages, so the word proves the family — but only over the entire value,
    so prose can never donate one. The year may be gone too."""

    row = _one("1991 Comp p 351")
    assert (row.authority_type, row.eo_compilation_start, row.eo_compilation_page) == (
        "eo_compilation",
        "1991",
        "351",
    )
    assert _one("Comp., p. 193").eo_compilation_page == "193"
    assert _one("see Comp. p. 193 for details").authority_type == "other"


def test_omb_names_itself_longhand_too() -> None:
    """The longhand "Office of Management and Budget Circular" reads as the same OMB Circular kind."""

    row = _one("Office of Management and Budget Circular No. A–25, as revised")
    assert (row.authority_type, row.admin_order_kind) == ("administrative_order", "OMB Circular")
    assert row.admin_order_number == "A-25"


def test_departmental_directive_systems_read_by_their_series_tokens() -> None:
    """FSM (Forest Service Manual — FSM 2320 is the wilderness chapter),
    DoD Directives, DOJ Orders and AG Orders, each web-verified 2026-08-22.
    Uppercase required, per the bare-EO rule."""

    for text, kind, number in [
        ("FSM 2320", "Forest Service Manual", "2320"),
        ("DODD 5000.35", "DoD Directive", "5000.35"),
        ("DOJ Order 2710.8A", "DOJ Order", "2710.8A"),
        ("AG Order 1687-93", "Attorney General's Order", "1687-93"),
    ]:
        row = _one(text)
        assert (row.authority_type, row.admin_order_kind, row.admin_order_number) == (
            "administrative_order",
            kind,
            number,
        ), text
    assert _one("fsm 2320").authority_type == "other"


def test_far_cites_title_48_by_its_own_declared_equivalence() -> None:
    """FAR 1.105-2: the regulation "may be referred to as ... the FAR", with
    "(FAR) 48 CFR 1.301" the parallel form — so "FAR 1.301" IS a CFR
    citation. Whole-value only; the English word "far" donates nothing."""

    row = _one("FAR 1.301")
    assert (row.authority_type, row.cfr_title, row.cfr_part) == ("cfr", 48, "1")
    assert _one("so far 1.301 applies").authority_type == "other"


def test_a_title_named_longhand_is_still_a_bare_title() -> None:
    """A bare "title 35 of the U.S.C." names the title with no section and is partial, not dropped."""

    row = _one("title 35 of the U.S.C.")
    assert (row.authority_type, row.usc_title, row.parse_status) == ("usc", 35, "partial")


def test_an_instrument_named_without_a_series_token_types_as_treaty() -> None:
    """CITES, the Chicago Convention and the Compacts of Free Association
    are typed by kind alone — partial, name visible, nothing minted. The
    implementing LEGISLATION is not the instrument: "... Convention Act"
    and "... Convention Implementation" stay refused."""

    for text in [
        "Convention on International Trade in Endangered Species of Wild Fauna and Flora (March 3, 1973)",
        "Article 12 of Convention on ICA",
        "Single Convention on Narcotic Drugs, 1961",
        "sec 141 of the Compacts of Free Association With the Federated States of Micron",
    ]:
        rows = parse_authority_citation(text)
        assert any(r.authority_type == "treaty" and r.parse_status == "partial" for r in rows), text
    assert _one("Chemical Weapons Convention Implementation Legislation Proposed").authority_type == "other"
    tunas = parse_authority_citation("Atlantic Tunas Convention Act of 1975, 16 U.S.C. 971 to 971k")
    assert not any(r.authority_type == "treaty" for r in tunas), "an implementing act is a statute"


def test_the_public_law_label_tolerates_its_hyphenated_spelling() -> None:
    """ "PL-111-134" hyphenates the label to its number; the "to"-separator
    form stays out of the grammar — it recovers only against the roster."""

    assert _one("PL-111-134").public_law == "111-134"
    assert _one("Pub. L. 111 to 203").authority_type == "other"


def test_a_subtitle_designator_does_not_hide_the_sections() -> None:
    """A subtitle designator between the title and its section list must not hide the listed sections."""

    rows = parse_authority_citation("46 USC subtitle II 3301, 3305, 3306")
    assert [r.usc_section for r in rows] == ["3301", "3305", "3306"]
    assert {r.usc_title for r in rows} == {46}


def test_the_appendix_marker_reads_in_any_case() -> None:
    """The appendix marker is recognized in uppercase, so "5 USC APP" reads as an appendix."""

    row = _one("5 USC APP (Ethics in Government Act of 1978)")
    assert (row.authority_type, row.usc_title, row.usc_appendix) == ("usc", 5, True)


def test_a_supreme_court_citation_is_read_under_its_own_scheme() -> None:
    """One column, two schemes. A bound opinion states its U.S. Reports
    citation; a slip opinion is not in a bound volume yet, so the same column
    states where it will appear. The publisher's filename is the
    discriminator: 608us1r32_*.pdf is bound, 24-43_*.pdf is slip. Measured
    over the 68-opinion term corpus: 31 bound, 37 slip, nothing unread."""
    bound = parse_supreme_court_citation(
        "608 U.S. 32", "https://www.supremecourt.gov/opinions/25pdf/608us1r32_g3bi.pdf"
    )
    assert bound.scheme == "us_reports"
    assert (bound.us_reports_volume, bound.us_reports_page) == (608, 32)

    slip = parse_supreme_court_citation("609/2", "https://www.supremecourt.gov/opinions/25pdf/24-43_2b35.pdf")
    assert slip.scheme == "preliminary_print"
    assert (slip.preliminary_print_volume, slip.preliminary_print_part) == (609, 2)
    assert slip.us_reports_volume is None


def test_a_part_locator_is_a_place_not_an_identity() -> None:
    """A preliminary-print part holds many opinions — the 37 slip opinions in
    the term corpus share four part keys. Reading the two schemes as one
    collides them onto a key that identifies nothing, which is why the
    volume/page and volume/part pairs are kept in separate columns."""
    first = parse_supreme_court_citation("609/2", "https://x/opinions/25pdf/24-43_a.pdf")
    second = parse_supreme_court_citation("609/2", "https://x/opinions/25pdf/24-621_b.pdf")
    assert first == second


def test_a_citation_disagreeing_with_its_url_is_left_unread() -> None:
    """A bound URL carrying a part locator states something the reader cannot
    resolve, so it says so rather than forcing the value into either scheme."""
    got = parse_supreme_court_citation("609/2", "https://x/opinions/25pdf/608us1r32_g.pdf")
    assert got.scheme == "unread"
    assert got.us_reports_volume is None and got.preliminary_print_volume is None


def test_a_stated_act_name_is_the_whole_name_and_only_the_name() -> None:
    """The name is whatever the publisher wrote, entire — and nothing beside
    it. "Ethics in Government Act" is the name; "Government Act" is not a law.
    Walking backwards over capitalized words and their connectors captures it
    whole, and stopping at citation-scheme tokens keeps the citation the name
    sits next to out of it: an earlier draft read "42 USC 7401 Clean Air Act"
    as "USC 7401 Clean Air Act" because it allowed bare four-digit tokens for
    years. A year is read from the trailing "of 1978" instead."""
    assert stated_act_name("5 USC (Ethics in Government Act of 1978)") == "Ethics in Government Act of 1978"
    assert stated_act_name("Pub. L. 95-521 Ethics in Government Act") == "Ethics in Government Act"
    assert stated_act_name("42 USC 7401 Clean Air Act") == "Clean Air Act"
    assert stated_act_name("sec 4, 15 USC 2603 Toxic Substances Control Act") == "Toxic Substances Control Act"
    assert stated_act_name("Truth in Lending Act") == "Truth in Lending Act"
    assert stated_act_name("the Clean Air Act") == "Clean Air Act"
    assert stated_act_name("DOJ Ord 1735.1") is None


def test_an_abbreviated_word_and_an_ampersand_do_not_end_the_name() -> None:
    """The walk stopped dead at an abbreviation mark and at a bare "&".

    "International Security & Development Coop. Act of 1981" (0420-AA10, 15
    rows) therefore stated NO name at all -- the grab could not end on a
    period -- and "Immigration & Nationality Act" stated its tail. Review #2
    named the first (notes/G.json). Both are one defect at the token, and the
    period is a mark ON the word rather than part of it, so every test the
    walk makes is made against the word without it.

    The name reported is the publisher's own SPAN. Rejoining the tokens with
    single spaces agrees on all 42,677 distinct values in this corpus today and
    stops agreeing the moment a word carries a mark: "U.S." is two tokens with
    nothing between them, and rejoining writes "U. S.".
    """

    assert (
        stated_act_name("International Security & Development Coop. Act of 1981, sec 601")
        == "International Security & Development Coop. Act of 1981"
    )
    assert stated_act_name("29 U.S.C. 794 (sec. 504 of the Rehab. Act of 1973)") == ("Rehab. Act of 1973")
    assert stated_act_name("16 USC 1801 et seq, Magnuson Fishery Conservation & Mgmt. Act") == (
        "Magnuson Fishery Conservation & Mgmt. Act"
    )
    # A middle initial is the same mark, and truncated the same way.
    assert (
        stated_act_name("sec. 19 of the Richard B. Russell National School Lunch Act, 42 U.S.C.1769a")
        == "Richard B. Russell National School Lunch Act"
    )
    assert (
        stated_act_name("H.R. 5956, Northern Mariana Islands U.S. Workforce Act of 2018, Pub. L. 115-218")
        == "Northern Mariana Islands U.S. Workforce Act of 2018"
    )
    assert stated_act_name("Section 212(d)(4)(C) of the Immigration & Nationality Act (INA)") == (
        "Immigration & Nationality Act"
    )
    # And the fences the walk already had, unmoved: a scheme token beside the
    # name stays out of it, a bare designator never opens a name, and a mark
    # on a word does not make a stop token into an ordinary one.
    assert stated_act_name("42 USC 7401 Clean Air Act") == "Clean Air Act"
    assert stated_act_name("Pub. L. 95-521 Ethics in Government Act") == "Ethics in Government Act"
    assert stated_act_name("division F of the National Defense Authorization Act") == (
        "National Defense Authorization Act"
    )
    assert stated_act_name("Sec. 504 of the Rehab. Act") == "Rehab. Act"

    # What this does NOT fix, recorded rather than hidden: the walk has never
    # crossed a comma, so a name with one inside it is still reported as its
    # tail. Before the mark was readable this value stated nothing at all; now
    # it states the part the walk can see, the same fragment shape the walk has
    # always produced elsewhere. 17 rows, every one of them already read as a
    # public law from its own "PL 104-227".
    assert stated_act_name("PL 104-227, Antarctic Science, Tourism and Conserv. Act of 1996") == (
        "Tourism and Conserv. Act of 1996"
    )


# --------------------------------------------------------------------------- #
# The 2026-08-22 grammar review. The tests above pin what the grammar reads;
# these pin the RULES it reads by — one test per shared expression, each
# written so that collapsing two rules that differ, or letting two copies of
# one rule drift apart, breaks it.


def test_one_section_token_serves_every_reader_of_the_code() -> None:
    """Six patterns wrote the U.S.C. section token out identically.

    That is one rule -- "digits and up to three trailing letters, optionally
    hyphenated to a second such token" -- and six copies of it are five
    chances for a widening in one reader to be a silent divergence from the
    other five. The token now has one name; this is the check that every
    reader still uses it, phrased as the shape only that token admits.
    """

    three_letters = "2000bb"  # RFRA: the ancestors' single-letter capture read 2000b + a stray b
    readers = {
        "abbreviated": f"42 U.S.C. {three_letters}",
        "appendix": f"42 U.S.C. app. {three_letters}",
        "transposed label": f"42 UCS {three_letters}",
        "title form": f"section {three_letters} of title 42",
        "list member": f"42 U.S.C. 1983, {three_letters}",
    }
    for name, text in readers.items():
        sections = {c.usc_section for c in parse_authority_citation(text)}
        assert three_letters in sections, f"{name} lost the three-letter suffix: {text!r}"
    # The self-naming code reads the same token without a title of its own.
    assert parse_authority_citation(f"I.R.C. {three_letters}")[0].usc_section == three_letters


def test_a_section_suffix_is_one_letter_repeated_and_must_end_the_token() -> None:
    """The ancestors' ``[A-Za-z]{0,3}`` invented tokens naming nothing.

    It took whatever letters followed the digits, capped at three, so a lost
    space produced "6921thr" out of "6921through 6927" and "2461not" out of
    "2461note" -- strings that appear in no text anywhere and that a consumer
    then joined on. 46 distinct such values, 113 occurrences, were published;
    the spicysearch consumer reported "33 U.S.C. 1251et" bridging confidently
    to a CFR part.

    The rule that separates them is the Code's own numbering convention: a
    section inserted between 106 and 107 is 106a, and when the single letters
    run out it goes 106aa, 106bb, never 106ab. Verified against OLRC's USLM
    release for the five densest titles (42, 20, 15, 12, 7): 18,136 sections,
    1,002 multi-letter suffixes, zero mixing two letters -- and "et", "to"
    and "and" appearing zero times among 319,777 numbered elements.
    """

    real = {
        "42 U.S.C. 2000bb": "2000bb",  # RFRA, doubled letter
        "20 U.S.C. 1087dd": "1087dd",
        "42 U.S.C. 1395ww": "1395ww",
        "42 U.S.C. 2000e": "2000e",  # single letter
        "16 U.S.C. 668dd": "668dd",
        "15 U.S.C. 77aaaa": "77aaaa",  # four letters: the cap truncated this
        "42 U.S.C. 300aa-15": "300aa-15",  # hyphenated compound
        "42 U.S.C. 1395w-114a": "1395w-114a",  # ... whose tail suffixes too
        "12 U.S.C. 1831p-1": "1831p-1",
    }
    for text, section in real.items():
        assert [c.usc_section for c in parse_authority_citation(text)] == [section], text

    # A lost space leaves the letters uncovered rather than fusing them in:
    # the digits are what the text states, and the letters stay visible.
    fused = {
        "28 USC 2461note": "2461",
        "33 USC 1311CWA sec 301": "1311",
        "42 U.S.C.425of the Social Security Act": "425",
        "15 USC 2605TSCA 6(e)(3)(B)": "2605",
    }
    for text, section in fused.items():
        rows = [c for c in parse_authority_citation(text) if c.authority_type == "usc"]
        assert rows[0].usc_section == section, text
        assert rows[0].parse_status == "partial", f"{text}: the letters are uncovered text"
    # Where the fused letters are a RANGE separator the tail is read, not just
    # left uncovered -- see the range test below. Here only the suffix matters:
    # the section is 6921, never "6921thr".
    assert parse_authority_citation("42 USC 6921through 6927")[0].usc_section == "6921"
    # "7401et seq" is the same repair reaching a different end: once "et" is
    # no longer part of the section, "et seq." is the ignorable tail it always
    # was, and the citation covers its whole value.
    covered = parse_authority_citation("42 USC 7401et seq")[0]
    assert (covered.usc_section, covered.parse_status) == ("7401", "ok")


def test_a_range_separator_is_a_word_and_its_space_may_be_lost() -> None:
    """Two gaps in one slot, both dropping a stated endpoint.

    "thru" was known to the compilation grammar and to no other, so
    "47 U.S.C. 151 thru 152" -- correctly spelled and correctly spaced --
    published section 151 and dropped 152. 9 distinct Agenda values, 35 rows.

    And the separator's space is optional, for the reason it is optional in
    the Register and Statutes labels: this publisher loses separator spaces.
    "42 USC 6921through 6927" and "5 USC 551to 557" are ranges whose separator
    merely lost its space. 21 further values, 36 rows.

    A DASH stays absent from the section grammar's separators, because among
    sections a hyphen may be part of one section's NAME -- which is what the
    ordering rule decides, and it still decides it.
    """

    ranged = {
        "47 U.S.C. 151 thru 152": ("151", "152"),
        "42 USC 6921through 6927": ("6921", "6927"),
        "5 USC 551to 557": ("551", "557"),
        "12 U.S.C. 1951 to1959": ("1951", "1959"),
        "42 U.S.C. 7401 to 7671q": ("7401", "7671q"),
        "42 U.S.C. 7401-7671q": ("7401", "7671q"),
    }
    for text, (start, end) in ranged.items():
        row = parse_authority_citation(text)[0]
        assert (row.usc_section, row.usc_section_end) == (start, end), text
    # A SPACED dash is a range separator; a bare one is not. A section's name
    # never contains a space, so the whitespace is what tells them apart --
    # and it has to, because admitting a bare dash takes the decision away
    # from the ordering rule and gets it wrong.
    spaced = parse_authority_citation("44 USC 3308 - 3314")[0]
    assert (spaced.usc_section, spaced.usc_section_end) == ("3308", "3314")
    compound = parse_authority_citation("12 USC 1702-1715z-21")[0]
    assert (compound.usc_section, compound.usc_section_end) == ("1702", "1715z")
    # A range endpoint is never the number that leads the NEXT citation.
    two = parse_authority_citation("7 U.S.C. 6501 - 7 U.S.C. 6524")
    assert [(c.usc_section, c.usc_section_end) for c in two] == [("6501", None), ("6524", None)]
    # The ordering rule is untouched: a compound NAME is still not a range,
    # and an unorderable pair is still refused whole.
    assert parse_authority_citation("12 U.S.C. 1831p-1")[0].usc_section_end is None
    assert parse_authority_citation("50 U.S.C. 4801-4582")[0].usc_section == "4801-4582"
    # A chapter range keeps the dash its own grammar allows, and still needs a
    # number behind it: "Ch. 34- The Peace Corps Act" names one chapter.
    assert parse_authority_citation("49 USC ch 201 to 213")[0].usc_chapter_end == "213"
    assert parse_authority_citation("22 USC Ch. 34- The Peace Corps Act")[0].usc_chapter_end is None


def test_a_pinpoint_is_read_back_off_the_citation_that_states_it() -> None:
    """``usc_section`` drops subsection detail; this reads it without moving it.

    The specimens are the visual review of 2026-08-23's § J rows: a pinpoint
    the pinned 1994 table resolves to ONE successor (``1651(b)(2)``), the bare
    sibling beside it, and the shapes that must NOT be read as pinpoints — a
    parenthesised YEAR after a range, a decimal delegation number, and a token
    that appears twice under two different pinpoints.
    """

    assert usc_section_pinpoint("49 USC 1651(b)(2)", "1651") == "(b)(2)"
    assert usc_section_pinpoint("49 USC 1651", "1651") is None
    assert usc_section_pinpoint("49 U.S.C. 553(b)(4)(B)", "553") == "(b)(4)(B)"
    assert usc_section_pinpoint("49 USC app 2704(a)(8)", "2704") == "(a)(8)"
    # A LABEL inside a parenthesis is not a second occurrence of the section:
    # the "(1)" of "15(1)" must not refuse the "(4)" written on section 1.
    assert usc_section_pinpoint("49 U.S.C. App. 1(4), 3(1), 15(1) (1988)", "1") == "(4)"
    assert usc_section_pinpoint("49 U.S.C. App. 1(4), 3(1), 15(1) (1988)", "15") == "(1)"
    # The paired negatives.
    assert usc_section_pinpoint("49 App. U.S.C. 1 to 85 (1988)", "85") is None, "a year is not a subsection"
    assert usc_section_pinpoint("42 U.S.C. 7401 et seq. (1990)", "7401") is None
    assert usc_section_pinpoint("49 U.S.C. 217(a), 1.51(F), 1.81, 1.85 and 1.90", "1") is None
    assert usc_section_pinpoint("49 U.S.C. 217(a), 1.51(F), 1.81, 1.85 and 1.90", "217") == "(a)"
    # Two spellings of one token refuse rather than pick the first.
    assert usc_section_pinpoint("49 USC 1354(a) to 1354(c)", "1354") is None
    assert usc_section_pinpoint("49 USC 1354(a) to 1354", "1354") is None
    # A folded token that is not the spelling the text uses finds nothing, and
    # says nothing: "80a-06" is where the zero-pad rule already spoke.
    assert usc_section_pinpoint("15 USC 80a-06(c)", "80a-6") is None
    assert usc_section_pinpoint("", "1651") is None
    assert usc_section_pinpoint("49 USC 1651(b)(2)", None) is None


def test_a_chapter_qualifier_governs_the_list_it_opens() -> None:
    """ "49 USC 106(g), ch 447 and 451" writes "ch" once and means it twice.

    RIN 2105-AD66, filed in fifteen editions from 2010-04 to 2018-10 (the
    visual review's § J row 8). The parse hands "451" on as a bare section
    token, so a reader downstream cannot see the qualifier — and the row it
    published answered about a repealed 1930s block instead of the current
    chapter 451 the filer cited. This says what the TEXT does; it does not
    say the token is a chapter (three corpus texts label real SECTIONS
    "chs.", and only a chapter register can tell those apart).
    """

    assert usc_token_is_chapter_qualified("49 USC 106(g), ch 447 and 451", "451") is True
    assert usc_token_is_chapter_qualified("49 U.S.C. 106(g), chapters 447 and 451", "451") is True
    assert usc_token_is_chapter_qualified("49 USC 106(g), chs. 447 and 451", "451") is True
    assert usc_token_is_chapter_qualified("49 USC ch 401, 411, and 417", "417") is True
    assert usc_token_is_chapter_qualified("49 USC 329 chs 401 and 417", "417") is True
    # The marker reaches FORWARD through a list and never backward over one.
    assert usc_token_is_chapter_qualified("49 USC 329 chs 401 and 417", "329") is False
    assert usc_token_is_chapter_qualified("49 USC 106(g), ch 447 and 451", "106") is False
    # A RANGE separator is not a list separator: "401 to 417" is the section
    # grammar's span, and _USC_CHAPTER reads a chapter range for itself.
    assert usc_token_is_chapter_qualified("49 USC 401 to 417", "417") is False
    assert usc_token_is_chapter_qualified("49 USC 1421 to 1431", "1431") is False
    assert usc_token_is_chapter_qualified("49 USC 1651(b)(2)", "1651") is False
    assert usc_token_is_chapter_qualified("49 USC 106(g), ch 447 and 451", None) is False


def test_a_plural_label_is_a_rule_not_a_roster() -> None:
    """The roster this replaced had drifted out of sync with the alternation.

    It listed "pts", which the label alternation could not capture at the
    time, so it tested for a spelling that could never arrive; and nothing
    anywhere said so. The rule -- a label is plural when it ends in "s",
    ignoring the abbreviation period the publisher may or may not write, or
    when it is the doubled section sign -- cannot drift, because it is
    computed from the label rather than compared against a second list of
    them.

    "pts"/"pts." became capturable on 2026-08-22, and this assertion is what
    noticed: a widening of the alternation arrives here rather than being
    forgotten, which is the whole point of deriving the roster from the
    grammar.
    """

    assert _every_capturable_label() == {
        "part",
        "parts",
        "pt",
        "pt.",
        "pts",
        "pts.",
        "sec",
        "sec.",
        "secs",
        "secs.",
        "section",
        "section.",
        "sections",
        "sections.",
        "§",
        "§§",
    }
    for label in _every_capturable_label():
        plural = citation_grammar._label_is_plural(label)
        expected = label == "§§" or label.rstrip(".").endswith("s")
        assert plural is expected, label
    # And the rule is load-bearing where it is used: only a plural label
    # licenses expansion under the prose policy.
    assert _parts("40 CFR parts 60, 61") == ["60", "61"]
    assert _parts("40 CFR part 60, 61") == ["60"]
    assert _parts("40 CFR §§ 60.1, 61.1") == ["60", "61"]
    assert _parts("40 CFR § 60.1, 61.1") == ["60"]


def _every_capturable_label() -> set[str]:
    """Every label spelling ``_CFR_STANDARD`` can actually put in its group.

    Derived from the grammar rather than typed out beside it, so a spelling
    added to the alternation arrives here instead of being forgotten.
    """

    found = set()
    for spelling in [
        "part",
        "parts",
        "pt",
        "pt.",
        "pts",
        "pts.",
        "sec",
        "sec.",
        "secs",
        "secs.",
        "section",
        "section.",
        "sections",
        "sections.",
        "§",
        "§§",
        "§§§",
        "chapter",
        "subpart",
    ]:
        match = citation_grammar._CFR_STANDARD.match(f"40 CFR {spelling} 60")
        if match is not None and match.group("label") is not None:
            found.add(match.group("label"))
    return found


def test_the_boundary_guard_is_applied_by_the_table_not_by_hand() -> None:
    """Four directive-system patterns each hand-wrote both guards.

    Four patterns times two ends is eight chances to omit one, and omitting
    one is silent: the pattern keeps matching, just also at offsets inside a
    longer token. The table applies the guards now, so this asserts the
    property for every entry rather than for the entries someone remembered.
    """

    samples = {
        "Forest Service Manual": "FSM 2320",
        "DoD Directive": "DODD 5000.35",
        "DOJ Order": "DOJ Order 2710.8",
        "Attorney General's Order": "AG Order 1687-93",
    }
    for pattern, kind in citation_grammar._DIRECTIVE_SYSTEMS:
        sample = samples[kind]
        assert pattern.search(sample), kind
        # The left guard: a citation may not begin inside a longer token.
        assert not pattern.search(f"x{sample}"), f"{kind}: began inside a longer token"
        # The right guard, stated as the guard rather than as one specimen's
        # number shape: whatever the pattern reads, it must end at a token
        # boundary. A trailing revision letter is part of some of these
        # numbers, so the probe appends more than one character.
        for probe in (f"{sample}9", f"{sample}zz"):
            found = pattern.search(probe)
            if found is not None:
                assert found.end() == len(probe) or not probe[found.end()].isalnum(), (
                    f"{kind}: ended inside a longer token in {probe!r}"
                )


def test_the_appendix_fence_and_the_reason_it_never_has_to_fire() -> None:
    """The fence is inert today, and what makes it inert is a marker set.

    Measured over the 42,642 distinct authority values the Agenda carries, no
    value exists where a plain U.S.C. match sits inside an appendix match --
    because "app" is not a section marker, so the plain reader finds nothing
    to match there at all. That is a property of the marker set, and a marker
    set is exactly the kind of thing a later reader widens, so the fence
    stays. This test states the reason: if "app" ever becomes readable as a
    section marker, this breaks and the fence starts earning its keep.
    """

    for text in ["50 U.S.C. app. 2401", "50 app USC 2071", "5 USC APP"]:
        assert not citation_grammar._USC_STANDARD.search(text), text
        rows = parse_authority_citation(text)
        assert all(row.usc_appendix for row in rows), text
    # And the appendix is a different place from the title proper, which is
    # the whole reason the fence is there.
    plain = parse_authority_citation("50 U.S.C. 2401")[0]
    assert plain.usc_appendix is False


def test_dash_normalization_replaces_one_character_with_one_character() -> None:
    """Spans on the normalized text must still index the original.

    Every rule in this module matches against the normalized text and reports
    a status derived from where the match sat; a table that changed a string's
    length would silently move every one of those offsets. Property, not
    example: the whole table, every entry, plus idempotence.
    """

    normalize = citation_grammar._normalize_dashes
    dashes = "‐‑‒–—―−\x96\x97"
    for dash in dashes:
        assert normalize(dash) == "-"
    for text in [dashes, f"PL 105{dashes}261", "42 U.S.C. 7401-7671q", "", "no dashes here"]:
        assert len(normalize(text)) == len(text), repr(text)
        assert normalize(normalize(text)) == normalize(text), repr(text)


# The families whose whole-value spelling the Agenda actually carries, one
# specimen each, with a prose frame that must turn "ok" into "partial". The
# specimens are corpus values, not invented ones.
_WHOLE_VALUE_FAMILIES = [
    ("usc", "5 U.S.C. 301"),
    ("usc_chapter", "49 U.S.C. ch. 311"),
    ("public_law", "PL 107-171"),
    ("statute_at_large", "106 Stat. 4777"),
    ("executive_order", "E.O. 13559"),
    ("case_citation", "550 U.S. 544"),
    ("presidential_document", "Proclamation 7383"),
    ("administrative_order", "212 DM 13"),
    ("treaty", "27 UST 1087"),
    ("revised_statute", "R.S. 463"),
    ("dc_code", "DC Code 24-131"),
    ("constitution", "U.S. Const., Art. II, Sec. 2"),
    ("reorganization_plan", "Reorganization Plan No. 3 of 1970"),
]


@pytest.mark.parametrize(("family", "value"), _WHOLE_VALUE_FAMILIES)
def test_a_status_is_a_function_of_the_span_a_family_covered(family: str, value: str) -> None:
    """One sentence, asserted for every family instead of for one of them.

    A match is a row, and a row is "ok" only when its own span leaves nothing
    behind but an ignorable tail. Twenty families restated that by hand
    before; a family that forgot -- or that hardcoded a status -- was invisible
    until someone read its block. Now it fails here.
    """

    covered = parse_authority_citation(value)
    assert [row.authority_type for row in covered] == [family], value
    assert covered[0].parse_status == "ok", value
    # The ignorable tails are the stated exception, and nothing else is.
    assert parse_authority_citation(f"{value} et seq.")[0].parse_status == "ok"
    assert parse_authority_citation(f"{value}, as amended")[0].parse_status == "ok"
    embedded = parse_authority_citation(f"as provided by {value} and elsewhere")
    assert embedded[0].parse_status == "partial", value


def test_the_families_that_can_never_cover_a_whole_value_say_so() -> None:
    """Deliberately NOT "ok" even when the match is the entire string.

    A date-identified presidential document carries a kind and no number; a
    Federal Register or CFR citation in the authority column locates a
    document rather than covering an authority; a bare title names a body of
    law rather than a provision. Each states less than the value does, so each
    is partial by rule rather than by span -- and the rule is worth a check,
    because "ok" here would tell a consumer the row was fully read.
    """

    for value in [
        "Presidential Memorandum of January 31, 2014",
        "Notice of August 3, 2000",
        "HSPD-12",
        "44 FR 56673",
        "3 CFR",
        "16 USC et seq",
        "FAR 1.301",
        "DFARS 201.3",
        "1991 Comp p 351",
        "Single Convention on Narcotic Drugs, 1961",
    ]:
        rows = parse_authority_citation(value)
        assert rows, value
        assert {row.parse_status for row in rows} == {"partial"}, value


# Values drawn from the Agenda's own authority column, chosen to exercise
# every branch: single citations, multi-family strings, damaged labels,
# placeholders, and text nothing can read.
_CORPUS_SHAPED_VALUES = [
    "5 U.S.C. 301",
    "5 U.S.C. 301; PL 95-91",
    "42 U.S.C. 1395, 1396, 1397",
    "50 USC app 2401 et seq",
    "3 CFR, 1977 Comp., p. 123",
    "EO 12924, 59 FR 43437, 3 CFR, 1994 Comp., p. 917",
    "Secretary of Labor's Order No. 12-71 (36 FR 8754), 8-76 (41 FR 25059)",
    "113 Stat. 1501A-293",
    "70A Stat. 157",
    "Not Yet Determined",
    "the Commissioner's general authority",
    "US Cost, Art II, sec 2",
    "21 UCS 374",
    "PL 105\x96261",
    "",
]


@pytest.mark.parametrize("value", _CORPUS_SHAPED_VALUES)
def test_the_invariants_every_authority_result_holds(value: str) -> None:
    """Five properties, measured true over all 42,642 distinct Agenda values.

    They are asserted here so that a future family cannot quietly break one:
    nothing vanishes (every input yields a row), the status vocabulary is
    closed, "ok" is a claim about the WHOLE value and so cannot be made twice,
    and a result never repeats itself.
    """

    rows = parse_authority_citation(value)
    assert rows, "nothing vanishes: every input yields at least one row"
    assert {row.parse_status for row in rows} <= {"ok", "partial", "failed"}
    if len(rows) > 1:
        assert all(row.parse_status == "partial" for row in rows), "one value, several authorities"
    if any(row.parse_status == "ok" for row in rows):
        assert len(rows) == 1, "'ok' says the citation covered the value; two cannot"
    assert len(set(rows)) == len(rows), "a result never repeats a row"
    # Parsing is a pure reading of the text: the same input, the same answer.
    assert parse_authority_citation(value) == rows


def test_the_list_grammars_are_three_rules_and_not_one() -> None:
    """They look like one rule. Collapsing them loses 19,167 rows.

    The CFR field and the Executive Order list are walked ANCHORED, item
    touching item, because those are structured values where the whole string
    is the citation. The U.S.C. list is scanned across a window instead, and
    that is not sloppiness: the Agenda's authority column writes subsection
    parentheticals, "note" tails and spelled ranges INSIDE its section lists
    -- "22 U.S.C. 214, 214 note, 1475e, 2504(a), 4201" -- and an anchored walk
    stops dead at the first one. Re-walking the U.S.C. lists anchored was
    measured over the corpus: 1,168 distinct values, 19,167 rows, would lose a
    real listed section. So the two shapes stay two rules.
    """

    # Anchored: the CFR list stops at prose rather than jumping over it.
    assert _parts("40 CFR parts 60, 61, and 63") == ["60", "61", "63"]
    assert _parts("40 CFR parts 60 as applied to sources built after 1971") == ["60"]
    # Windowed: the U.S.C. list steps over a parenthetical and a note tail,
    # which is the whole reason it is not anchored.
    stepped = parse_authority_citation("22 U.S.C. 214, 214 note, 1475e, 2504(a), 4201")
    assert {row.usc_section for row in stepped} >= {"214", "1475e", "2504", "4201"}
    spanned = parse_authority_citation("18 USC 3521 to 3528, 3621, 3622")
    assert {row.usc_section for row in spanned} >= {"3621", "3622"}


def test_the_executive_order_list_asks_for_no_plural_label() -> None:
    """The comment said a plural label licenses the list. The code never
    checked, and the corpus is why it must not: "E.O. 11302, 13520" and
    "EO 10577, 11222, 11478, and 12106" write the label singular and list
    anyway (3 distinct Agenda values, measured 2026-08-22). The rule is the
    structured field's rule -- the whole value is the citation -- and it is
    now written down where it is enforced."""

    plural = parse_authority_citation("Executive Orders 13990 and 14008")
    assert [row.executive_order for row in plural] == ["13990", "14008"]
    singular = parse_authority_citation("E.O. 11302, 13520")
    assert [row.executive_order for row in singular] == ["11302", "13520"]
    listed = parse_authority_citation("EO 10577, 11222, 11478, and 12106")
    assert [row.executive_order for row in listed] == ["10577", "11222", "11478", "12106"]


def test_treaty_volume_bounds_differ_because_the_series_do() -> None:
    """The two volume bounds LOOK like a copy-paste divergence.

    They are each their own series' fact: U.S.T. ran 1950-1984 and its volumes
    are three digits; the U.N. Treaty Series is past three thousand volumes.
    Merging them onto one bound would be the clever abstraction that is worse
    than the duplication, so this pins that they are different on purpose.
    """

    ust = parse_authority_citation("27 UST 1087")[0]
    assert (ust.treaty_series, ust.treaty_volume) == ("UST", 27)
    unts = parse_authority_citation("1870 UNTS 167")[0]
    assert (unts.treaty_series, unts.treaty_volume) == ("UNTS", 1870)
    # A four-digit volume is not a U.S.T. volume; the pattern does not read it
    # as one, and no reader may quietly widen it to match UNTS.
    assert not any(row.treaty_series == "UST" for row in parse_authority_citation("1870 UST 167"))


def test_a_federal_register_page_reads_through_its_leading_zeros() -> None:
    """ "62 FR 04670" occurs in the Agenda's own timetable field. Page zero
    does not exist and stays unread, which is what keeps the zero-padding
    rule from becoming "any digits at all"."""

    assert [(c.volume, c.page) for c in parse_federal_register_citations("62 FR 04670")] == [(62, 4670)]
    assert parse_federal_register_citations("62 FR 0") == ()
    # Uppercase is the evidence, here as everywhere else in this module.
    assert parse_federal_register_citations("62 fr 4670") == ()


def test_the_cfr_grammars_overlap_and_one_citation_stays_one_citation() -> None:
    """Three spellings can read "40 CFR part 60"; the keyword ones defer.

    Without the deferral each spelling contributes its own row and one
    citation becomes two or three. The check is the count, because the
    duplicate rows would otherwise all be individually correct.
    """

    for text in ["40 CFR part 60", "title 40, part 60", "title 40, Code of Federal Regulations, part 60"]:
        citations = parse_cfr_citations(text)
        assert [(c.cfr_title, c.cfr_part) for c in citations] == [(40, "60")], text


def test_the_next_citation_lookahead_names_every_family_this_module_reads() -> None:
    """A list member is never the number that LEADS another citation.

    The guard named U.S.C., CFR and Stat -- and not the Federal Register,
    though this module has read FR citations since the timetable builder
    needed them. That omission harvested phantom sections out of FR VOLUME
    numbers: "5 U.S.C. 301, ... 71 FR 4219" published a section 71 of title
    5. Measured before the guard was completed: 5 distinct values, 85 rows,
    three phantom sections (5 U.S.C. 71 from "71 FR", 22 U.S.C. 44 from "44
    FR", 50 U.S.C. 83 from "83 FR").

    The rule is stated once per family so the next family added to the module
    has an obvious place to fail.
    """

    for tail in ["15 U.S.C. 78c", "36 CFR 1.5", "117 Stat. 429", "71 FR 4219", "86 Fed. Reg. 8267"]:
        rows = parse_authority_citation(f"5 U.S.C. 301, {tail}")
        # Scoped to TITLE 5: a following citation may well state a section of
        # its own title -- "15 U.S.C. 78c" does -- and that is a second
        # citation, not a list member. What must never happen is its leading
        # number being filed under the title on its left.
        listed = {row.usc_section for row in rows if row.authority_type == "usc" and row.usc_title == 5}
        assert listed == {"301"}, f"{tail} donated {listed - {'301'}} to title 5's section list"
    # The guard rejects; it never swallows. A real list still expands.
    listed = parse_authority_citation("5 U.S.C. 301, 302, 303")
    assert {row.usc_section for row in listed} == {"301", "302", "303"}


def test_a_label_repair_is_inert_on_a_label_that_is_not_damaged() -> None:
    """Eleven repairs spelled the code label out by hand; one name now.

    That name reads LESS than the reading grammar does -- no annotated
    edition, no "U.S. Code" longhand -- because a repair rewrites the label it
    matched and so may only recognize what it can rewrite. The checkable half
    of that is inertness: over the 42,642 distinct Agenda authority values,
    the 17 repairs touch 79 between them, and the four intact spellings of the
    code label are not among them. 63 of the 79 predate
    "dropped-c-in-usc-label", whose 3 are pinned in
    :func:`test_a_bare_volume_us_page_is_a_code_citation_with_a_lost_c`, 3
    more are "code-label-on-a-treaty-series", pinned in
    :func:`test_a_treaty_series_outranks_the_code_label_it_wears`, and 10 are
    "letter-o-for-zero-in-usc-section", pinned in
    :func:`test_the_o_for_zero_homoglyph_damages_a_section_too`.

    This docstring said 62 while the true figure was 63, because a prose
    number with no check behind it drifts. The count is now ASSERTED against
    the specimens below rather than narrated, so the next widening either
    updates it or fails here.
    """

    for intact in ["50 U.S.C.A. 4701", "38 USCS 3564", "49 U.S. Code 106", "5 U.S.C. 301"]:
        assert citation_grammar._repair_whole_value_label(intact) == intact, intact
        assert parse_authority_citation(intact)[0].authority_type == "usc"
    # Damaged, and repaired to a label the grammar then reads.
    for damaged, section in [("49 SC 30166", "30166"), ("19 U.S.C.. 3314", "3314"), ("12 (U.S.C. 2243)", "2243")]:
        assert parse_authority_citation(damaged)[0].usc_section == section, damaged
    # A repair is anchored to the whole value, so prose can never donate one.
    assert parse_authority_citation("filed under 49 SC 30166 last year")[0].authority_type == "other"
    # The table's size, so the docstring's count and the table cannot drift
    # apart silently again; its reach over the corpus is recounted in
    # :func:`test_every_named_label_repair_reaches_the_corpus`.
    assert len(citation_grammar._WHOLE_VALUE_LABEL_REPAIRS) == 17


def test_a_section_marker_may_not_begin_a_longer_word() -> None:
    """ "sec" starts ordinary words, and the marker had no right-hand boundary.

    So "Social Security Act" offered "Sec" as a marker and handed "urity" to
    the capture behind it; "Secretary" gave "retary", "Securities" gave
    "urities", "SECURE 2.0" gave "URE". 2,350 rows of the published artifact
    carried a sliced-up word as a section number (measured 2026-08-22).

    Worse than the noise: the slice was the LEFTMOST match, so it hid the
    real citation further along the same string. "... of the Social Security
    Act, sec 1102" reported "urity" and never reached 1102. Fixing the
    boundary recovered a real section on 244 distinct values, not merely
    blanked a wrong one.
    """

    for prose in [
        "of the Social Security Act",
        "Secretary of Agriculture",
        "Securities Exchange Act",
        "Bank Secrecy Act",
        "Secretarial Orders 3299 and 3302",
        "the Secure and Trusted Communications Networks Act of 2019",
    ]:
        assert citation_grammar.stated_section(prose) is None, prose
    # A real marker still reads, in every spelling -- including the plural,
    # whose own "s" the old marker took as the section number.
    assert citation_grammar.stated_section("sec 326") == "326"
    assert citation_grammar.stated_section("sec 1819(a) of the Social Security Act") == "1819(a)"
    assert citation_grammar.stated_section("sections 114(a)(3), 503(b)") == "114(a)(3)"
    assert citation_grammar.stated_section("SECURE 2.0 Act of 2022, sec. 127") == "127"
    # The recovery, not just the refusal: the real section behind the word.
    assert citation_grammar.stated_section("1102 of the Social Security Act, sec 1102") == "1102"


def test_an_acts_amendments_are_a_different_act_and_keep_their_name() -> None:
    """The reader walked backwards from "Act" and stopped there.

    "Amendments" sits between the word and the year, so the name came out
    truncated and the year then attached to the wrong head: "Clean Air Act
    Amendments of 1990" was published as "Clean Air Act". 67 distinct Agenda
    values, 291 rows.

    That is not lost precision, it is a different law's name in a column
    whose only job is to say what the value named -- and the OLRC's own index
    says so, holding both as separate entries. Worse on 36 of those rows, the
    truncated name is not an entry at all: there is no "Lacey Act", only the
    Lacey Act Amendments of 1981.
    """

    whole = {
        "Clean Air Act Amendments of 1990": "Clean Air Act Amendments of 1990",
        "Clean Air Act Amendments of 1990, sec 112": "Clean Air Act Amendments of 1990",
        "PL 106-245, Radiation Exposure Compensation Act Amendments of 2000": "Radiation Exposure Compensation Act Amendments of 2000",
        "sec 3 of the Higher Education Act Amendments": "Higher Education Act Amendments",
        "Lacey Act Amendments, 16 U.S.C. 3371 et seq.": "Lacey Act Amendments",
        "PL 102-569, The Rehabilitation Act Amendments of 1992": "Rehabilitation Act Amendments of 1992",
    }
    for text, name in whole.items():
        assert stated_act_name(text) == name, text
    # The base spellings, and every other tail shape, are unchanged.
    assert stated_act_name("42 USC 7401 Clean Air Act") == "Clean Air Act"
    assert stated_act_name("5 USC (Ethics in Government Act of 1978)") == "Ethics in Government Act of 1978"
    # Capitalization is the evidence here as everywhere: "the 1990 Clean Air
    # Act amendments" is prose ABOUT the act, not the amending act's name.
    assert stated_act_name("Section 320 of the 1990 Clean Air Act amendments") == "Clean Air Act"


def test_a_normalized_name_is_a_fixed_point() -> None:
    """A join key must survive being normalized again, or nothing can ask for it.

    Until 2026-08-22 the edge-strip ran before the quote-straightening, and the
    four names OLRC writes with TeX quotes came out with a leading ``''`` this
    very function would have stripped — so the key the artifact stored was one
    no query could ever spell. Straightening first fixes all four; the order is
    the whole fix.
    """

    for written, key in (
        ("``SPARS'' Act", "spars'' act"),
        ("``Kick-Back'' Racket Act", "kick-back'' racket act"),
        ("``Seeing-Eye'' Dogs on Railroads Act", "seeing-eye'' dogs on railroads act"),
        (
            "``Six Triple Eight'' Congressional Gold Medal Act of 2021",
            "six triple eight'' congressional gold medal act of 2021",
        ),
    ):
        assert normalize_popular_name(written) == key, written
        assert normalize_popular_name(key) == key, written
    # RefSpec also asserts the property over every name the Popular Name Tool
    # publishes; that half reads RefSpec's pinned index and stays there.


def test_an_unresolvable_value_still_states_what_it_states() -> None:
    """A statement is not a resolution. "Sec 326, National Defense
    Authorization Act" names an act family and a section while naming no
    particular year's NDAA -- and there is one nearly every year -- so the
    name is worth carrying and the identity is not."""

    row = parse_authority_citation("Sec 326, National Defense Authorization Act")[0]
    assert (row.authority_type, row.parse_status) == ("other", "failed")
    assert row.stated_act_name == "National Defense Authorization Act"
    assert row.stated_section == "326"
    assert row.act_key is None, "a stated name is never an identity"
    # The reader is a reader, not a shape-matcher: a value that states no
    # section behind a marker states no section.
    assert parse_authority_citation("1921 et seq.")[0].stated_section is None


def test_the_statutes_volume_bound_reaches_the_volume_now_being_printed() -> None:
    """Volume 140 carries the 2026 session laws, and the bound stopped at 139.

    The bound is a damage detector, not a parser fence: the builder computes
    ``stat_volume_in_series`` as ``1 <= volume <= STAT_VOLUME_HIGHEST_KNOWN``,
    so a stale bound turns the newest real volume into a reported impossibility.
    Nothing in the pinned capture cites 140 yet (the editions stop at 202510),
    which is exactly why this is the moment to move it -- the correction costs
    nothing today and the next edition would have paid for it.

    Both directions are pinned. 140 is real: Pub. L. 119-101, the 21st Century
    ROAD to Housing Act, approved July 11 2026, runs 140 Stat. 846-984
    (govinfo PLAW-119publ101; archives.gov's current-session listing gives the
    same first page). 199 is the corpus's own flagged value and must stay
    outside, so this is a widening of one volume and not the removal of a
    bound.
    """

    top = parse_authority_citation("140 Stat. 846")[0]
    assert (top.authority_type, top.statute_volume, top.statute_page) == ("statute_at_large", 140, 846)
    assert 1 <= top.statute_volume <= citation_grammar.STAT_VOLUME_HIGHEST_KNOWN
    flagged = parse_authority_citation("199 Stat 594")[0]
    assert flagged.statute_volume == 199
    assert not 1 <= flagged.statute_volume <= citation_grammar.STAT_VOLUME_HIGHEST_KNOWN


def test_no_citation_begins_inside_a_hyphenated_number() -> None:
    """ "Pub. L. 109-162 Stat. 3051" published a Statutes volume 162.

    ``_LEFT`` fences a citation against starting inside a longer WORD, and a
    hyphen is neither a digit nor a letter -- so the Statutes reader was free
    to start at the second half of a Public Law number and call it a volume.
    The publisher's string is missing its volume (Pub. L. 109-162 begins at
    119 Stat. 2960, and its sec. 607 begins at 119 Stat. 3048, so page 3051
    is real and volume 162 is ours). The flag ``stat_volume_in_series`` was
    firing on RefSpec's own invention.

    Six distinct values, 9 source rows, every one a phantom volume; no real
    citation anywhere in the corpus begins immediately after a digit-hyphen.

    One of the six was RIGHT BY COINCIDENCE and is refused anyway:
    "Title II, PL 106-113 Stat. 1501A-293" -- Pub. L. 106-113 does begin at
    113 Stat. 1501, so the digits next door happened to be the volume. Reading
    them was still a guess; it is right once in six. A consumer holding the
    Public Law roster can recover that one under a roster-existence fence, and
    that fence is not the grammar's to hold.
    """

    rows = parse_authority_citation("sec. 607, Pub. L. 109-162 Stat. 3051")
    assert [(row.authority_type, row.public_law) for row in rows] == [("public_law", "109-162")]
    assert not any(row.statute_volume for row in rows), "162 is the law's number, not a volume"
    # Nothing vanishes: the uncovered "Stat. 3051" keeps the row partial, so a
    # consumer studying publisher damage can still see the string fell short.
    assert rows[0].parse_status == "partial"
    # The coincidence, refused on purpose.
    coincidence = parse_authority_citation("Title II, PL 106-113 Stat. 1501A-293")
    assert [row.authority_type for row in coincidence] == ["public_law"]
    # A volume the publisher actually states still reads, hyphen next door or not.
    stated = parse_authority_citation("Pub. L. 117-58, 135 Stat. 429")
    assert [(row.authority_type, row.statute_volume, row.statute_page) for row in stated] == [
        ("public_law", None, None),
        ("statute_at_large", 135, 429),
    ]


def test_a_public_law_label_between_a_code_and_its_section_is_not_a_public_law() -> None:
    """ "31 USC PL 5311-5314" lost twice: a phantom law, and no U.S.C. row.

    The Bank Secrecy Act is 31 U.S.C. 5311-5314, and the stray "PL" between
    the code name and the sections both minted a Public Law numbered by a
    Congress that has never sat and blocked the U.S.C. reader from its own
    section span. The same office writes the undamaged form 68 times
    ("31 USC 5311 to 5314" x66, "31 USC 5311-5314" x2).

    The fence is the numbered series, which is why this is a reading and not a
    guess: no 5,311th Congress has legislated, so the Public Law reading is
    impossible, while the U.S.C. reading covers the whole string. Exactly one
    survivor.

    It must NOT fire where the label is real. The same agency writes
    "31 USC PL 107-56 Bank Secrecy Act" (and three further spellings, 9 rows
    together) where Pub. L. 107-56 -- the USA PATRIOT Act, which amended the
    Bank Secrecy Act -- is a genuine citation sitting beside a bare title.
    Congress 107 is in series, so the operator never sees those rows.
    """

    rows = parse_authority_citation("31 USC PL 5311-5314")
    assert [(row.authority_type, row.usc_title, row.usc_section, row.usc_section_end) for row in rows] == [
        ("usc", 31, "5311", "5314")
    ]
    for real in (
        "31 USC PL 107-56 Bank Secrecy Act",
        "31 USC PL107-56 Bank Secrecy Act",
        "31 USC P L 107-56 Bank Secrecy Act",
        "12 U.S.C. Pub. L. 116--136, 134 Stat. 281",
    ):
        assert any(row.public_law is not None for row in parse_authority_citation(real)), (
            f"{real}: a Public Law whose congress is in series is a Public Law"
        )


def test_a_sentinel_wearing_a_zero_title_still_states_nothing() -> None:
    """ "00 CFR None" is the publisher's form saying nothing, with a numeral on.

    ``states_nothing("None")`` is True and 4,453 bare rows correctly carry a
    NULL title; ``states_nothing("00 CFR None")`` was False, so 36 rows were
    reported as an impossible CFR title instead of as the placeholder they
    are. Census over both pinned tables: "00 CFR NYD" 16 rows, "00 CFR None"
    15, "00 CFR 00" 3, "0 CFR 00" 1, "00 USC 00" 1.

    The detector now looks past a leading ZERO title, and past nothing else.
    Two facts license exactly that much:

    * Title 0 exists in neither code in any year. This is not the CFR-35
      mistake -- title 35 held the Panama Canal and a 1990s citation to it is
      real -- because no volume of either code has ever been numbered 0. So
      the numeral cannot be a citation, and the only thing left for it to be
      is the form's zero-fill.
    * What follows must be a sentinel in its own right, or itself all zeros.
      A part or section numbered 0 exists in neither code either, so
      "00 CFR 00" locates nothing at all.

    That second half is the fence, and it earns its keep on one row:
    "0 CFR 150 to 189" (RIN 2070-AC97, ed 199510) is a TRUNCATED REAL
    CITATION, not a sentinel -- the same RIN, same ordinal, writes
    "40 CFR 150 to 189" in ed 199604 and every edition after. It keeps its
    impossible-title flag, which is the flag doing its job.
    """

    for placeholder in ("00 CFR NYD", "00 CFR None", "00 CFR 00", "0 CFR 00", "00 USC 00", "00 USC NYD"):
        assert citation_grammar.states_nothing(placeholder), placeholder
        assert parse_cfr_citations(placeholder) == (), f"{placeholder} locates nothing"
        row = parse_authority_citation(placeholder)[0]
        assert (row.authority_type, row.parse_status) == ("unstated", "failed"), placeholder
    # The truncated real citation, and the bare forms, both unchanged.
    assert not citation_grammar.states_nothing("0 CFR 150 to 189")
    (ranged,) = parse_cfr_citations("0 CFR 150 to 189")
    assert isinstance(ranged, CfrCitationRange)
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in (ranged.start, ranged.end)] == [
        (0, "150", False),
        (0, "189", False),
    ]
    assert citation_grammar.states_nothing("None") and citation_grammar.states_nothing("NYD")
    # A real title is never looked past: "40 CFR None" would be a real title
    # beside a sentinel, which is a different statement and not this one.
    assert not citation_grammar.states_nothing("40 CFR None")


def test_a_parenthesised_year_does_not_turn_a_code_citation_into_a_case() -> None:
    """ "318 USC 363 (1942)" is *Clearfield Trust*, and this grammar will not say so.

    Twelve rows at Treasury RIN 1510-AB25 -- "318 USC 363 (1942)" and
    "332 USC 234 (1947)", 6 rows each -- are the *United States Reports*:
    Clearfield Trust Co. v. United States, 318 U.S. 363, and United States v.
    Munsey Trust Co., 332 U.S. 234. The proof is in the dataset: the
    predecessor RIN for the same regulation, 1510-AA45, writes them
    "318 US 363 (1943)" and "332 US 234 (1947)", which this grammar already
    reads correctly as case citations. This test pins the REFUSAL, with the
    numbers that force it, so nobody closes the gap by keying on the year.

    Three measurements refuse it, each fatal on its own:

    1. **A parenthesised year is not a case marker in this corpus; it is the
       Bluebook EDITION year of the Code.** 247 rows across 59 distinct values
       type as ``usc`` while carrying one -- "49 USC app 1 to 85 (1988)" (22
       rows), "28 U.S.C. 2461 note (1990)" (13), "5 U.S.C. 301 (2018)" (8).
       That is more than twice the entire case-citation population (107 rows,
       22 values). The year is evidence of nothing.
    2. **On these very rows the year is WRONG.** Clearfield Trust was decided
       in 1943 and the filer typed 1942, so a year-consistency fence -- the
       one honest use of the year -- refuses the row we would be trying to
       reach.
    3. **There are two survivors, not one.** The operator that reaches the
       case reading is a single-character insertion ("US" -> "USC"), and the
       identical single-character operator class reaches a DAMAGED U.S.C.
       title from the same digits ("318 USC" -> "18 USC", exactly as
       "115 USC 78o(d)" -> "15 USC 78o(d)"). Of the 34 distinct
       impossible-title values in this corpus, 32 resolve to a damaged Code
       title and 2 to U.S. Reports. The damaged reading is the usual one.

    What tells the two apart is the predecessor RIN spelling them "US". That
    is data, not a rule -- an oracle the grammar does not hold and should not
    grow. A consumer joining editions can label these; this reader cannot.
    """

    for text, title, section in (("318 USC 363 (1942)", 318, "363"), ("332 USC 234 (1947)", 332, "234")):
        rows = parse_authority_citation(text)
        assert [(r.authority_type, r.usc_title, r.usc_section) for r in rows] == [("usc", title, section)]
        assert not any(r.case_volume for r in rows), "the case reading needs an oracle this module lacks"
        assert citation_grammar.usc_title_is_possible(title) is False, "and the row is still flagged"
    # The undamaged sibling spelling reads as the case it is, unchanged.
    for text, volume, page in (("318 US 363 (1943)", 318, 363), ("332 US 234 (1947)", 332, 234)):
        row = parse_authority_citation(text)[0]
        assert (row.authority_type, row.case_volume, row.case_page) == ("case_citation", volume, page)


def test_a_code_citation_may_carry_a_parenthesised_year_too() -> None:
    """The periodless-case reader's stated reason was false; its fence is not.

    Its comment read "case citations carry one [a parenthesized year], code
    citations never do". They do, constantly: the Bluebook cites a specific
    edition of the Code that way, and this corpus writes 247 such rows across
    59 distinct values. The real discriminator is narrower and empirical --
    a periodless "US", with no C anywhere, plus a year -- and it is worth
    knowing that it holds by measurement rather than by principle.

    Measured over all 42,642 distinct values: every periodless "US" that
    reaches this reader is one of the two U.S. Reports citations, and every
    code citation written periodless ("50 US 2401 et seq", "42 US 2201",
    "15 US 1392", "30 US 820", "49 US 44719") carries no year. A value that
    were BOTH -- a lost C and an edition year -- would be misread, and none
    exists.
    """

    edition_years = [
        "49 USC app 1 to 85 (1988)",
        "28 U.S.C. 2461 note (1990)",
        "5 U.S.C. 301 (2018)",
        "43 U.S.C. 1457c (2018)",
    ]
    for text in edition_years:
        types = {row.authority_type for row in parse_authority_citation(text)}
        assert "case_citation" not in types, f"{text}: an edition year is not a decision year"
        assert "usc" in types, text
    # The periodless code citations the corpus actually carries: no year, and
    # so no case reading to compete with.
    for text in ("50 US 2401 et seq", "42 US 2201", "15 US 1392", "30 US 820", "49 US 44719"):
        assert not any(row.case_volume for row in parse_authority_citation(text)), text


def test_nara_writes_a_volume_an_issue_and_a_page_range() -> None:
    """ "89-61; 21436-21437" is Vol. 89 No. 61, pages 21436-21437.

    Three Direct Final Rules from the National Archives, all in edition
    202410, are well formed under a grammar this module did not know:
    ``<volume>-<issue number>; <first page>-<last page>``. They are not
    damaged citations, and no damage operator is involved -- the citation
    "89 FR 21436" is DERIVABLE from the value, volume being the number before
    the dash and page the number before the second dash.

    Verified independently today, three of three, on every field:

    ===================  ==================  ==========================
    value                govinfo issue       Federal Register (by RIN)
    ===================  ==================  ==========================
    89-61; 21436-21437   FR-2024-03-28       2024-06406, 89 FR 21436-21437,
                         vol 89, issue 61    RIN 3095-AC17, 2024-03-28
    89-85; 35007-35008   FR-2024-05-01       2024-09396, 89 FR 35007-35008,
                         vol 89, issue 85    RIN 3095-AC12, 2024-05-01
    89-105 ; 46803-46805 FR-2024-05-30       2024-11910, 89 FR 46803-46805,
                         vol 89, issue 105   RIN 3095-AC18, 2024-05-30
    ===================  ==================  ==========================

    The row's own date matches the publication date in all three. The issue
    number is confirmed rather than needed: the citation derives from the
    text alone, and govinfo merely says what the middle number is.

    Measured over all 671,959 timetable rows, this shape matches 3 rows and
    all 3 are currently ``failed`` -- it never touches an ``ok``,
    ``positional``, ``relabeled`` or ``absent`` row.
    """

    for text, volume, page in (
        ("89-61; 21436-21437", 89, 21436),
        ("89-85; 35007-35008", 89, 35007),
        ("89-105 ; 46803-46805", 89, 46803),
    ):
        read = citation_grammar.parse_agenda_timetable_citation(text)
        assert (read.scheme, read.volume, read.page) == ("nara-issue", volume, page), text
    # The ordinary form is not this reader's business: the builder's own FR
    # grammar reads it, and a second reader for it would be a second answer.
    assert citation_grammar.parse_agenda_timetable_citation("89 FR 91529").scheme == "unread"


def test_a_page_the_publisher_never_wrote_gets_a_name_not_a_guess() -> None:
    """Five rows carry a volume and no page anywhere in the text.

    Three of them have the row's OWN RIN suffix where the page belongs --
    0648-AT97 -> "70 FR AT97", 0648-AU91 -> "72 FR AU91", 0790-AK07 ->
    "83 FR AK07". That is checkable against the row's own ``rin`` column with
    no oracle and no guessing, and measured over all 671,959 rows the
    predicate matches exactly 3 rows, all of them currently ``failed``.

    Reading them as pages produces three real, wrong pages -- 70 FR 97,
    72 FR 91, 83 FR 7 all exist, in the opening days of their volumes -- so a
    range check would never catch the error. The page was never written. The
    correct disposition is a LABEL, not a parse.

    The other two are the same family reached by a different route: a value
    that stops after the label ("71 FR", "72 FR", "85 FR" -- 5 rows) and a
    page of five zeros ("86 FR 00000" -- 1 row), which is exactly the width
    of an FR page and is a template placeholder written before the OFR
    assigned one. Six rows together, every one currently ``failed``.
    """

    for text, rin, volume in (
        ("70 FR AT97", "0648-AT97", 70),
        ("72 FR AU91", "0648-AU91", 72),
        ("83 FR AK07", "0790-AK07", 83),
    ):
        read = citation_grammar.parse_agenda_timetable_citation(text, rin=rin)
        assert (read.scheme, read.volume, read.page) == ("page-is-the-rin-suffix", volume, None), text
    # Without the row's own RIN the claim cannot be made, so it is not made.
    assert citation_grammar.parse_agenda_timetable_citation("70 FR AT97").scheme == "unread"
    # A suffix that is not this row's suffix is not this row's evidence.
    assert citation_grammar.parse_agenda_timetable_citation("70 FR AT97", rin="0648-BK86").scheme == "unread"
    for text, volume in (("71 FR", 71), ("72 FR", 72), ("85 FR", 85), ("86 FR 00000", 86)):
        read = citation_grammar.parse_agenda_timetable_citation(text)
        assert (read.scheme, read.volume, read.page) == ("page-unstated", volume, None), text


def test_a_document_number_is_not_a_page_and_says_so() -> None:
    """ "90-21215" is a Federal Register DOCUMENT number, not a volume/page.

    21215 is the sequence half of FR document 2025-21215, which is 90 FR
    54242, "Internal Governance", a CSB Rule published 2025-11-26 -- exactly
    the date the row states, by exactly the agency that owns the RIN
    (verified against federalregister.gov today; the OFR tags that document
    RIN 3301-AA02 while the agenda row is 3301-AA03, so one register has the
    wrong final character and the document itself is not in doubt).

    The positional reading is not merely unsupported, it is REFUTED: 90 FR
    21215 is a real page -- the first page of the issue of 2025-05-19 -- six
    months before the row's own date, on a day the CSB published nothing.

    What the text alone yields is the volume and the document number, because
    volume-to-year is a bijection (volume = year - 1935). The PAGE needs the
    Register, so no page is stated here. Measured over all 671,959 rows this
    shape matches 1 row, and it is ``failed``.
    """

    read = citation_grammar.parse_agenda_timetable_citation("90-21215")
    assert (read.scheme, read.volume, read.page) == ("fr-document-number", 90, None)
    assert read.fr_document_number == "2025-21215"
    # The NARA form is told apart by its own punctuation, not by its numbers:
    # it carries a semicolon and a page range, and an FR volume has ~250
    # issues, so a five-digit second number is no issue number.
    assert citation_grammar.parse_agenda_timetable_citation("89-61; 21436-21437").scheme == "nara-issue"


def test_the_positional_fence_is_one_named_edit_and_the_reason_it_stops_there() -> None:
    """The residue set's stated reason was false; its boundary is exactly right.

    The builder admits a positional reading when the value's non-digit residue
    is in an enumerated set, and its comment says "NFR", "DR", "FSR" "stay
    refused: no single named operation derives them from FR". That is FALSE --
    insertion and substitution are as ordinary as the deletion and
    transposition already in the set. Measured here so the boundary can be
    stated as what it is: Damerau-Levenshtein distance from "FR".

    The whole residue space is 18 values, measured over all 671,959 rows:

    * DL 0 -- ``FR``
    * DL 1 -- ``-FR``, ``/FR``, ``CFR``, ``DR``, ``F``, ``FR-``, ``FRX``,
      ``FSR``, ``NFR``, ``R``, ``RF``
    * DL 2 -- ``(empty)``, ``-``, ``FRAK``, ``FRAT``, ``FRAU``, ``FRFR``

    Widening the enumeration to DL <= 1 admits 91 rows by residue, but 85 of
    them (``CFR`` 64 relabeled, ``-FR`` 16 ok, ``FR-`` 5 ok) are consumed by
    an EARLIER branch and never reach the positional one. The rows whose
    status actually changes are the 6 currently failed: ``FRX`` x3, ``DR``,
    ``FSR``, ``NFR`` -- every one independently corroborated, zero overfire.

    Widening to DL <= 2 admits 4 more and is wrong on all four, invisibly:
    ``70 FR AT97`` -> 70 FR 97, ``72 FR AU91`` -> 72 FR 91, ``83 FR AK07`` ->
    83 FR 7, ``90-21215`` -> 90 FR 21215. Each lands on a page that really
    exists, so no range check catches it. The fence holds not because the
    operators past it are unnameable but because THE SECOND NUMBER IN THOSE
    FOUR VALUES IS NOT A PAGE -- in three it is the digits inside the RIN's
    own suffix, and in the fourth a document-number sequence.
    """

    edits = citation_grammar.damerau_levenshtein
    assert edits("FR", "FR") == 0
    for residue in ("-FR", "/FR", "CFR", "DR", "F", "FR-", "FRX", "FSR", "NFR", "R", "RF"):
        assert edits(residue, "FR") == 1, residue
    for residue in ("", "-", "FRAK", "FRAT", "FRAU", "FRFR"):
        assert edits(residue, "FR") == 2, residue
    # Transposition is one edit, which is what makes this Damerau and not
    # plain Levenshtein: "RF" is the label transposed, and plain edit distance
    # would call it two.
    assert edits("RF", "FR") == 1
    assert citation_grammar.FR_LABEL_MAX_EDITS == 1, "DL<=2 is wrong on all four rows it admits"


def test_a_dates_comma_is_not_a_list_separator() -> None:
    """ "(Repealed ... on or after November 1, 1987)" published 18 U.S.C. 1987.

    The section-list walk reads ", NNNN" as another listed section, and a
    written-out date puts a comma in front of its year. 131 distinct values,
    896 source rows, measured 2026-08-22 over all 42,642 distinct authority
    values: every one of them minted a phantom section out of a year. The
    dominant shape is the Bureau of Prisons' own repeal parenthetical, which
    the agency copies forward edition after edition.

    Refusing four-digit year-like numbers WOULD NOT WORK, and the sharpest
    proof is the very number this defect minted. There is no 18 U.S.C. 1987 --
    but 42 U.S.C. 1987 is real, "Prosecution of violation of certain laws"
    (uscode.house.gov, verified 2026-08-22), and this corpus cites both it and
    42 U.S.C. 1984 as themselves. The number is not the discriminator; the
    month and day in front of the comma are. That is derivable from the text
    under one declared convention -- the US month-day-year date -- and needs
    no oracle.

    (This docstring first offered "5 U.S.C. 2006" as the real section. It is
    not one: uscode.house.gov returns "the document you were looking for does
    not exist". The claim was written from memory and not checked, which is
    the mistake this repo keeps writing down. The rule never depended on it.)

    The removed sections are exactly ten years -- 1935, 1951, 1979, 1984,
    1987, 1992, 1996, 2006, 2018, 2020 -- and no value gained a row.
    """

    repeal = "18 USC 3621, 3622, 3624, 4001, 4042, 4081, 4082 (Repealed in part as to offenses committed on or after November 1, 1987)"
    sections = [row.usc_section for row in parse_authority_citation(repeal)]
    assert sections == ["3621", "3622", "3624", "4001", "4042", "4081", "4082"]
    assert "1987" not in sections, "the year is the repeal date, not an eighth section"

    # Every spelling the corpus writes the date in, each a distinct value.
    for text, expected in (
        ("18 U.S.C. 4082 (repealed in part as to offenses committed on or after Nov. 1, 1987)", ["4082"]),
        ("18 USC 5006 to 5024 (Repealed October 12, 1984, as to offenses committed)", ["5006"]),
        # The publisher loses the space after the comma; the date is the same date.
        (
            "18 USC 751, 3621, 4082 (Repealed ... on or after November 1,1987), 4161-4166",
            ["751", "3621", "4082", "4161"],
        ),
        # A BARE date, no parentheses anywhere: the month and day still hold.
        ("31 USC 9701 Act of August 31, 1951, 65 Stat. 290", ["9701"]),
        ("7 USC 612c, sec 32 of the Act of August 24, 1935", ["612c"]),
        ("49 U.S.C. 30301 note (Pub. L. 116-260, div. U, title X, Dec. 27, 2020)", ["30301"]),
    ):
        listed = [row.usc_section for row in parse_authority_citation(text) if row.authority_type == "usc"]
        assert listed == expected, text

    # And a real section that happens to look like a year keeps its row: the
    # rule is about the date, never about the number. Both listed sections
    # below exist -- 42 U.S.C. 1987 "Prosecution of violation of certain laws"
    # and 42 U.S.C. 1988 "Proceedings in vindication of civil rights".
    for text, expected in (
        ("42 U.S.C. 1983, 1987, 1988", ["1983", "1987", "1988"]),
        ("42 U.S.C. 1395, 1996, 1997", ["1395", "1996", "1997"]),
    ):
        assert [row.usc_section for row in parse_authority_citation(text)] == expected, text


def test_an_acts_own_name_may_carry_its_year_across_a_comma() -> None:
    """ "Consolidated Appropriations Act, 2018" published 22 U.S.C. 2018.

    The same sentence as the date rule, about a different writer of commas.
    The older drafting convention puts an act's year after a comma where the
    modern one writes "of 2018", and the U.S. Code's own headings keep it --
    the Shipping Act, 1916; the Merchant Marine Act, 1920; the Revenue Act,
    1926. The comma belongs to the act's NAME, so the year behind it is not a
    listed section.

    2 distinct values, 2 source rows, measured 2026-08-22. Small, and it is
    the same wrong answer the 896-row date population was: a real-looking
    section nothing flags.

    The word "Act" is required. A bare ", 2018" may genuinely list a section
    and is left alone, which is why this is a rule about a naming convention
    rather than about four-digit numbers.
    """

    helms = (
        "the Helms, Biden, 1978, and 1985 Amendments, 22 U.S.C. 2151b(f), e.g., "
        "Consolidated Appropriations Act, 2018, Pub. L. 115-141, Div. K, sec. 7018)"
    )
    assert [row.usc_section for row in parse_authority_citation(helms) if row.authority_type == "usc"] == ["2151b"]
    # The older naming convention, spelled the way the Code's own headings do.
    for text, expected in (
        ("46 USC app 876(e) to 876(l) Merchant Marine Act, 1920", ["876"]),
        ("22 U.S.C. 2151b, Foreign Assistance Act, 1961", ["2151b"]),
    ):
        listed = [row.usc_section for row in parse_authority_citation(text) if row.authority_type == "usc"]
        assert listed == expected, text
    # A comma with no act's name in front of it still separates a list.
    assert [row.usc_section for row in parse_authority_citation("22 U.S.C. 2151b, 2018")] == [
        "2151b",
        "2018",
    ]


def test_a_rin_shaped_token_is_never_a_listed_section() -> None:
    """ "..., 3235-AE17." published 15 U.S.C. 3235 -- the RIN's agency prefix.

    The third thing a bare number behind a comma can be, beside a date's year
    and an act's year. The Agenda names its own rulemakings with a Regulation
    Identifier Number -- four digits for the agency, then two letters and two
    digits -- so a filer who says which sibling rulemaking a document was
    published under leaves a four-digit number sitting behind a comma, and the
    section-list walk lists it under whatever title the last citation named.

    SEC RIN 3235-AH12's Fall 1998 continuation is the specimen and the whole
    population. Measured over all 42,642 distinct authority values the pinned
    artifact carries plus all 98 ADDITIONAL_INFO continuations, exactly two
    values write a RIN-shaped token at all: this one, and "1904-AG07: 42
    U.S.C. 16251", where the token LEADS the value so no list separator
    precedes it and no row's section ever came from it. So this fence moves
    nothing in the published table -- the damage lives in the continuation
    strings, which is where filers mention each other's RINs.

    The sibling shape was measured and REFUSED. A Federal Register document
    number is ``\\d{2,4}-\\d{3,6}``, and 1,536 rows over 455 distinct
    (value, title, section) triples in the pinned table are that shape -- every
    one of them a real U.S.C. RANGE the standard form read ("50 U.S.C.
    4801-4852", 256 rows; "28 U.S.C. 509-510", 48; "42 U.S.C. 6291-6309", 22).
    Fencing that would delete real citations. The two letters between the
    hyphen and the trailing digits are what make the RIN shape unambiguous,
    and they are why only it is fenced.
    """

    continuation = (
        "15 USC 80a-8; 15 USC 80a-29; 15 USC 80a-30; 15 USC 80a-37; 15 USC 80a-1 et seq; "
        "15 USC 80a-34(b); 15 USC 80a-39; 15 USC 77g; 15 USC 80a-24. The proposed and final "
        "rules were mistakenly published in the Federal Register under the RIN of a related "
        "rulemaking, 3235-AE17."
    )
    rows = parse_authority_citation(continuation)
    assert [row.usc_section for row in rows] == [
        "80a-8",
        "80a-29",
        "80a-30",
        "80a-37",
        "80a-1",
        "80a-34",
        "80a-39",
        "77g",
        "80a-24",
    ]
    assert all(row.usc_title == 15 for row in rows)

    # The fence is the token's shape and nothing else: a four-digit number that
    # IS a section still lists, on either side of a fenced one, and the RIN
    # never stops the walk that steps over it.
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 3235, 1988")] == [
        "1983",
        "3235",
        "1988",
    ]
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 3235-AE17, 1988")] == [
        "1983",
        "1988",
    ]
    # And the token's own trailing digits are not a section either: "AE17"
    # never reaches the walk, because a list member starts with a digit.
    assert "17" not in {row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 3235-AE17")}
    # Lowercase is not the publisher's spelling of a RIN and is not fenced: no
    # value in the corpus writes one, and inventing a case fold here would
    # start guessing at four-digit numbers the corpus never showed.
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 3235-ae17")] == [
        "1983",
        "3235",
    ]


def test_a_compilation_locators_year_and_page_are_never_listed_sections() -> None:
    """ "31 USC 9701; 3 CFR, 1982 Comp., p. 166" published 31 U.S.C. 1982.

    The fourth thing a bare number behind a comma can be, beside a date's
    year, an act's year and a RIN's agency prefix: a number the Title 3
    COMPILATION LOCATOR beside it owns. A locator names a volume and a page,
    the family beside this one already types it as ``eo_compilation``, and the
    section-list walk read its numbers as sections of whatever title the last
    citation named.

    Two values, one Justice RIN (1115-AD44), 13 rows of 31 U.S.C. 1982 -- the
    volume YEAR, harvested behind "31 USC 9701". Its sibling values write the
    same locator with the page bare and a semicolon in the head, "3 CFR; 1982
    Comp., 166", and there the PAGE was harvested instead: 7 rows of 31
    U.S.C. 166. Both numbers belong to the page E.O. 12356 was printed on, and
    the value says so itself -- it names the order and the Register citation
    ("EO 12356; 47 FR 14874") in the same breath.

    The fence is the locator's whole span rather than its year, because the
    notes write the shape the Agenda's own values do not: "E.O. 10577, 3 CFR,
    1954-58 Comp., p. 218" hands the walk "1954-58", which the ordering rule
    then EXPANDS into an abbreviated span of five sections of title 3. One
    rule covers the year, the abbreviated closing year, the span between them
    and the page, because all four are numbers the locator owns.

    Over the 8,240 pinned authority notes this fence and its dotted sibling
    remove 1,260 note citations in 792 notes and add none; the compilation
    half of that is every "3 CFR, NNNN Comp." a note writes after a U.S.C.
    citation, which is 600 notes' worth of E.O. provenance.
    """

    for text, phantom in (
        ("31 USC 9701; 3 CFR, 1982 Comp., p. 166; 8 CFR part 2.", "1982"),
        ("31 USC 9701; 3 CFR, 1982 Comp, p 166; 8 CFR part 2.", "1982"),
        ("31 USC 9701; EO 12356; 47 FR 14874; 3 CFR; 1982 Comp., 166; 8 CFR part 2.", "166"),
    ):
        rows = parse_authority_citation(text)
        assert [row.usc_section for row in rows if row.authority_type == "usc"] == ["9701"], text
        assert phantom not in {row.usc_section for row in rows}, text
        # Nothing vanishes: the locator is still on the record, as the thing it
        # is. The third value gains that row rather than keeping a section.
        locator = [row for row in rows if row.authority_type == "eo_compilation"]
        assert [(row.eo_compilation_start, row.eo_compilation_page) for row in locator] == [("1982", "166")], text

    # The note spelling, where the fenced number is a SPAN and not one section.
    rows = parse_authority_citation("E.O. 10577, 3 CFR, 1954-58 Comp., p. 218")
    assert [row.authority_type for row in rows] == ["executive_order", "eo_compilation"]
    assert [row.usc_section for row in rows] == [None, None]

    # PAIRED NEGATIVE. The fence is the locator's span and nothing wider: a
    # four-digit number that IS a listed section still lists, including one
    # that reads like a year, and a list running INTO a locator keeps every
    # member up to it.
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1982, 1983, 1988")] == [
        "1982",
        "1983",
        "1988",
    ]
    assert [
        row.usc_section
        for row in parse_authority_citation("42 U.S.C. 1982, 1983; 3 CFR, 1982 Comp., p. 166")
        if row.authority_type == "usc"
    ] == ["1982", "1983"]
    # And a Comp-less single year is still a CFR part, not a locator, so the
    # fence cannot reach a number the grammar never diverted.
    comp_less = parse_authority_citation("42 U.S.C. 1983, 1990; 3 CFR 1990")
    assert [row.usc_section for row in comp_less if row.authority_type == "usc"] == ["1983", "1990"]
    assert [row.cfr_part for row in comp_less if row.authority_type == "cfr"] == ["1990"]


def test_a_statutes_at_large_pinpoint_page_is_marked_not_refused_or_believed() -> None:
    """ "101 Stat. 1568, 1608" reads 12 U.S.C. 1608 -- the Act's own second
    page (Bluebook "volume Stat. start, pinpoint"), not a section of
    anything. A sibling of the RIN, compilation-locator and named-comma
    fences above, in a class none of them covers: those three always REFUSE
    (a number that belongs to another family is never a section); this one
    cannot, because the identical shape is sometimes a genuinely resumed
    U.S.C. list -- 14 CFR 121's own authority note continues a real 49
    U.S.C. list after "126 Stat. 89" with 44101, 44701-44702, and more, all
    real aviation-safety sections.

    So :data:`AuthorityCitation.usc_section_after_statute` is a MARK, not a
    verdict: this module has no section-existence oracle to ask (the oracle
    imports it, so the reverse is circular) and cannot tell a pinpoint page
    from a resumed section by shape alone. A consumer that CAN reach the
    oracle decides -- see
    :func:`refspec.registry.cfr_authority_notes.read_note_citations` for the
    note-side gate this fence feeds -- and this test only proves the mark
    lands on the right members and nowhere else.

    Both specimens are pinned RAW: 12 CFR 615's own authority note (research/
    evidence/ecfr-authority-notes-2026-08-24/notes.jsonl) and 14 CFR 121's
    (same cache; the note also names 46105 after the resumed list, reached by
    the SEPARATE title-carry mechanism and therefore never marked at all).
    """

    farm_credit = (
        "Secs. 4.2, 4.9, 5.9, 5.17, 5.19 of the Farm Credit Act (12 U.S.C. 2153, 2160, 2243, 2252, 2254); "
        "sec. 424, Pub. L. 100-233, 101 Stat. 1568, 1656 (12 U.S.C. 2252 note); "
        "sec. 514, Pub. L. 102-552, 106 Stat. 4102, 4134."
    )
    marks = {
        (row.usc_title, row.usc_section): row.usc_section_after_statute
        for row in parse_authority_citation(farm_credit)
        if row.authority_type == "usc"
    }
    # The list BEFORE any Stat. citation is untouched.
    assert marks[(12, "2153")] is False
    assert marks[(12, "2254")] is False
    # "1656" is the pinpoint page of "101 Stat. 1568, 1656" -- marked, never
    # emitted as a bare unmarked section.
    assert marks[(12, "1656")] is True
    # A SECOND Stat. citation further in the same value marks its own page
    # too -- the fence is not a one-shot flag that stops firing.
    assert marks[(12, "4134")] is True

    faa = (
        "49 U.S.C. 106(f), 40103, 40113, 40119, 41706, 42301 preceding note added by Pub. L. 112-95, "
        "sec. 412, 126 Stat. 89, 44101, 44701-44702, 44705, 44709-44711, 44713, 44716-44717, 44722, "
        "44729, 44732; 46105; Pub. L. 111-216, 124 Stat. 2348 (49 U.S.C. 44701 note); "
        "Pub. L. 112-95, 126 Stat. 62 (49 U.S.C. 44732 note); "
        "Pub. L. 115-254, 132 Stat. 3186 (49 U.S.C. 44701 note)."
    )
    faa_marks = {
        (row.usc_title, row.usc_section): row.usc_section_after_statute
        for row in parse_authority_citation(faa)
        if row.authority_type == "usc"
    }
    # The stated head list is untouched, whichever spelling reached it.
    assert faa_marks[(49, "106")] is False
    assert faa_marks[(49, "42301")] is False
    # The GENUINELY resumed list, reached only by scanning past "126 Stat.
    # 89", is marked exactly like the fabrication above -- the module cannot
    # and must not tell them apart.
    assert faa_marks[(49, "44101")] is True
    assert faa_marks[(49, "44701")] is True
    assert faa_marks[(49, "44732")] is True
    # "46105" stands behind a SEMICOLON, not a comma/and/or, so this reader
    # never reaches it at all -- it is not a listed member of anything here.
    # (``cfr_authority_notes.read_note_citations`` reaches it by its own
    # separate title-carry mechanism, unmarked, because no Stat. citation
    # sits in ITS OWN segment; that is a different reader's test.)
    assert (49, "46105") not in faa_marks


def test_a_dotted_number_behind_a_comma_is_a_cfr_section_not_a_listed_one() -> None:
    """ "33 U.S.C. 1903(b) ... Sections 155.480, 155.490" published 33 U.S.C. 155.

    The fifth, and the one the number refutes on its own face: the U.S. Code
    has no dotted section. "155.490" is part 155, section 490 of a CFR title,
    and the Coast Guard's own part-155 authority statement writes a whole
    sentence of them after a U.S.C. citation.

    Measured over all 42,677 distinct authority values, this fence moves eight
    values and 31 rows, every one of them a delegation regulation cited by its
    CFR address inside a U.S.C. list: 47 U.S.C. 1 (22 rows over five values,
    "and secs. 1.407 and 1.411" behind "47 U.S.C. 154(i), 201, 302a, 303"),
    49 U.S.C. 1 (5 rows, "1.51(F), 1.81, 1.85 and 1.90" behind "49 U.S.C.
    217(a)"), 7 U.S.C. 51 (2 rows, "7 USC 15b and 51.65") and 33 U.S.C. 155
    (2 rows, the specimen). None of them loses its box: every one of those
    values states a real U.S.C. citation the fence does not touch.

    In the notes it is the larger half of the pair -- "7 CFR 2.22, 2.80, and
    371.3" behind an APHIS note's "21 U.S.C. 136 and 136a" published 21 U.S.C.
    2 and 21 U.S.C. 371, and 21 U.S.C. 371 is real, so the phantom was
    indistinguishable from a citation downstream.

    The fence is the dot BEFORE A DIGIT, so a sentence-ending period after the
    last listed section is untouched, and it is scoped to the LIST TAIL: a
    dotted number anywhere else is either anchored to a code name, where the
    dot stays an uncovered tail and the row reads "partial", or read by the
    CFR grammar, which spells the dot itself.
    """

    coast_guard = "Sections 155.480, 155.490, 155.750(e), and 155.775 are also issued under 46 U.S.C. 3703."
    assert [(row.usc_title, row.usc_section) for row in parse_authority_citation(coast_guard)] == [(46, "3703")]
    fcc = "47 U.S.C. 154(i), 201, 302a, 303, and secs. 1.407 and 1.411"
    assert [row.usc_section for row in parse_authority_citation(fcc)] == ["154", "201", "302a", "303"]
    aphis = "21 U.S.C. 136 and 136a; 7 CFR 2.22, 2.80, and 371.3."
    assert [
        (row.usc_title, row.usc_section) for row in parse_authority_citation(aphis) if row.authority_type == "usc"
    ] == [
        (21, "136"),
        (21, "136a"),
    ]

    # PAIRED NEGATIVE. A list still ends with a period, and a hyphenated
    # section name is not a dotted one -- the two shapes the fence must not
    # reach.
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 1988.")] == [
        "1983",
        "1988",
    ]
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 1395w-4")] == [
        "1983",
        "1395w-4",
    ]
    # And the dot only fences where a DIGIT follows it: "1983, 1988. 42" is a
    # sentence boundary the walk still reads through.
    assert "1988" in {row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 1988. See also.")}

    # THE ONE INSTANCE THE GUARD IS NARROWED FOR, and the reason it is narrowed
    # to a single token. 12 CFR 326's note ends "31 U.S.C. 5311-5314,
    # 5316-5332.2", where the "2" is the publisher's SUPERSCRIPT FOOTNOTE
    # MARKER flattened into the text -- the same part's heading flattens the
    # same one, "PART 326-MINIMUM SECURITY DEVICES AND PROCEDURES AND BANK
    # SECRECY ACT 1 COMPLIANCE". A guard over the span would have deleted the
    # Bank Secrecy Act's own range from the note that grants it, and taken two
    # rows of 31 U.S.C. 5318 (RIN 3064-AC19) from "present" to "near-miss".
    # It is the only hyphen-before-a-dot in 42,677 values and 8,240 notes.
    fdic = "12 U.S.C. 1813, 1815, 1817, 1818, 1819 (Tenth), 1881-1883, 5412; 31 U.S.C. 5311-5314, 5316-5332.2."
    spans = [
        (row.usc_title, row.usc_section, row.usc_section_end)
        for row in parse_authority_citation(fdic)
        if row.usc_section_end is not None
    ]
    assert spans == [(31, "5311", "5314"), (12, "1881", "1883"), (31, "5316", "5332")]
    # And the refusal it replaces is WHOLE where it does fire: a fenced item
    # never publishes its own first endpoint with the far end dropped.
    assert "110" not in {row.usc_section for row in parse_authority_citation("46 U.S.C. 3703 and 110.25-1")}


def test_a_dotted_number_anchoring_a_usc_citation_is_a_cfr_section_too() -> None:
    """ "26 USC 1.104-1(c)" is 26 CFR 1.104-1, and truncating at the dot mints
    a real but WRONG U.S.C. section: 26 U.S.C. section 1 exists (the income
    tax rate schedule) and has nothing to do with the regulation.

    2026-09-01: the dotted fence above shipped scoped to the list tail on the
    stated assumption that a dotted number reached ANCHORED to a code name
    stays visibly "partial" and so does no silent harm -- measured false. A
    consumer reading ``usc_title``/``usc_section`` and the section-existence
    oracle without also checking ``parse_status`` sees an affirmative,
    fabricated "exists": 155 rows / 31 RINs by the mined ledger's own regex,
    41 distinct values / 175 rows / 36 RINs / 89 currently-``exists`` rows by
    a full grammar replay (``research/evidence/reg-dot-fence-2026-09-01/``,
    trusted over the narrower regex because it also catches truncation the
    regex's anchored-only shape does not, e.g. the appendix form below).

    The refusal REFUSES THE MATCH ENTIRELY here rather than narrowing it (no
    "26 U.S.C. 1" row at all, not even a wrong one) -- but see the paired
    list-continuation case: refusing the match must not cost real LISTED
    members that follow the same anchor.
    """

    assert parse_authority_citation("26 USC 1.104-1(c)") == (
        citation_grammar.AuthorityCitation(authority_type="other", parse_status="failed"),
    )
    assert parse_authority_citation("26 USC 1.1502") == (
        citation_grammar.AuthorityCitation(authority_type="other", parse_status="failed"),
    )

    # PAIRED POSITIVE, the collateral-damage case a naive regex-level refusal
    # at this position first shipped with in testing: "40 U.S.C. 102.01, 322,
    # 5331" (RIN 2105-AE58) must refuse the fabricated anchor "102" (truncated
    # from "102.01") while KEEPING the members listed behind it. A
    # regex-level refusal on the required anchor slot would have taken
    # usc_matches -- and so the whole list-tail scan -- down with the
    # fabricated section.
    #
    # WHAT THE RAW RECORD SAYS, read AROUND the match rather than at it
    # (output/registry-real-data-sources/unified-agenda-editions/
    # REGINFO_RIN_DATA_201804.xml line ~141247): this RIN's CFR_LIST is "49
    # CFR 40", and the repository's own pinned note for that part reads
    # "Authority: 49 U.S.C. 102, 301, 322, 5331, 20140, 31306, and 54101 et
    # seq." (research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl).
    # The filer's TWO authority boxes together -- this one and "40 U.S.C.
    # 31306 and 54101 et seq." beside it -- reproduce that publisher list
    # member for member under the WRONG TITLE, 49 read as 40. So "102.01" is
    # damage to a real title-49 list rather than a number invented from
    # nothing, and 322 and 5331 are the real members standing behind it.
    #
    # WHICH LEAVES A RESIDUAL THIS FENCE DOES NOT REACH, named rather than
    # implied: the surviving 40:322 is an affirmative "exists" under a title
    # the filer got wrong (49 U.S.C. 322 is what the note grants), and
    # 40:5331 is not a title-40 section at all -- it reads "absent", where 49
    # U.S.C. 5331 is real. That is the same class as the 8 CFR 281 residual
    # test_cfr_authority_notes documents: an oracle answers "does this
    # identity exist", never "did the filer mean this identity". Repairing a
    # stated TITLE is a different unit from refusing a truncated SECTION, and
    # this fence is the second one.
    gsa = parse_authority_citation("40 U.S.C. 102.01, 322, 5331")
    assert [row.usc_section for row in gsa if row.authority_type == "usc"] == ["322", "5331"]
    assert "102" not in {row.usc_section for row in gsa}

    # The appendix form's OWN section slot truncates the same way, and is a
    # separate reader (_USC_APPENDIX) from the anchor above: "46 app USC
    # 1241.1" truncated to appendix section 1241. Its slot is OPTIONAL, so a
    # refusal there degrades to a title-only appendix citation instead of
    # losing the match -- no list-tail dependency to protect, unlike the
    # anchor.
    appendix = parse_authority_citation("46 app USC 1241.1")
    assert appendix == (
        citation_grammar.AuthorityCitation(
            authority_type="usc", parse_status="partial", usc_title=46, usc_appendix=True
        ),
    )

    # MUTATION-BATTERY FIND: an early version of this fence guarded the bare
    # digit run without an atomic group, and the engine backtracked "102"
    # (refused: dot-digit follows) down to "10" (accepted: "2" is not a dot)
    # -- mis-narrowing to a DIFFERENT wrong section instead of refusing.
    # "10" must never appear for this value under any future edit.
    assert "10" not in {row.usc_section for row in gsa}
    # That assertion is BORROWED protection, though, not load-bearing: at the
    # anchor the row is withheld by _usc_leading_section_is_untruncated
    # whatever the regex matched, so "10" stays out even with the atomic
    # group deleted (measured by deleting it, 2026-09-01 -- only the appendix
    # and transposed-label slots move, to appendix 124 and 40:10). The
    # transposed label has no second line of defence -- its section slot IS
    # the combinator and the pattern ends there -- so the direct probe goes
    # here, and this is one of the two assertions that dies with the group.
    # Constructed rather than measured: no corpus value transposes the
    # letters of a truncated citation, which the pattern's own comment says.
    assert parse_authority_citation("40 UCS 102.01") == (
        citation_grammar.AuthorityCitation(authority_type="other", parse_status="failed"),
    )

    # PAIRED NEGATIVE, the one measured exception: a dot NOT owned by the
    # anchor at all, corroborated by reading the raw record (RIN 0938-AO69,
    # output/registry-real-data-sources/unified-agenda-editions/
    # REGINFO_RIN_DATA_200610.xml line 82048; CFR_LIST there is "45 CFR 5b").
    # "552a" is the Privacy Act, a complete real section on its own, and the
    # filer ran a second citation directly against it with no separator --
    # the dot leads straight into an explicit "CFR", so the fence must not
    # fire.
    privacy_act = parse_authority_citation("5 USC 552a.45 CFR s 5b.11(b) (2)(ii)(H)")
    assert [(row.usc_title, row.usc_section) for row in privacy_act if row.authority_type == "usc"] == [(5, "552a")]
    # The carve-out is ONE string read two ways -- _DOT_TRUNCATION_SIGNATURE,
    # compiled as _DOT_TRUNCATES_A_SECTION for the anchor above and embedded
    # as the _A_DOTTED_NUMBER_IS_A_CFR_SECTION lookahead in every in-pattern
    # section slot -- and the specimen above exercises only the first. This
    # is the assertion that dies when the second one loses it: the same
    # dot-into-CFR shape reached as a LISTED member. Constructed, not
    # measured (the corpus's single specimen sits at the anchor), and here
    # because a guard spelled once has to be provable at both of its readers.
    # That was the whole hazard of the two copies: deleting the carve-out
    # from either one alone left the other still covering the specimen, so
    # neither copy's test could see its own guard go missing.
    listed = parse_authority_citation("5 USC 551, 552a.45 CFR s 5b.11(b) (2)(ii)(H)")
    assert [row.usc_section for row in listed if row.authority_type == "usc"] == ["551", "552a"]

    # The Internal Revenue Code self-name is read in the SAME loop as the
    # anchor and refused the same way.
    assert parse_authority_citation("I.R.C. 1.6103") == (
        citation_grammar.AuthorityCitation(authority_type="other", parse_status="failed"),
    )
    assert [row.usc_section for row in parse_authority_citation("I.R.C. 337(d)")] == ["337"]

    # PAIRED NEGATIVE. A genuine, spelled range reaching a dotted endpoint
    # stays untouched at this position too -- the SAME footnote-marker
    # exception the list-tail test above proves, reached without a list at
    # all ("31 USC 5316 to 5332.2" is the standalone form of the same 12 CFR
    # 326 note range).
    footnote_range = parse_authority_citation("31 USC 5316 to 5332.2")
    assert [(row.usc_section, row.usc_section_end) for row in footnote_range] == [("5316", "5332")]

    # THE LATENT SHAPE, pinned so that a real specimen cannot land quietly.
    # _USC_TITLE_FORM spells its refusal INSIDE the pattern at the "first"
    # slot, so a dotted FIRST member costs the WHOLE citation and every real
    # member behind it -- the collateral loss the anchor above is built to
    # avoid by withholding one row instead. The position is measured EMPTY:
    # replaying that reader with and without the guard over all 42,677
    # distinct authority values and all 8,240 notes changes 0 texts
    # (2026-09-01), so no withhold-only-the-row machinery is built for it,
    # per structure-earns-its-keep. The day a specimen appears, this is the
    # assertion that fails and forces the conversation.
    assert parse_authority_citation("sections 102.01, 322 of title 40") == (
        citation_grammar.AuthorityCitation(authority_type="other", parse_status="failed", stated_section="102.01"),
    )
    # ...and the undamaged spelling of the same citation reads in full, which
    # is exactly what that refusal would cost.
    assert [row.usc_section for row in parse_authority_citation("sections 322, 5331 of title 40")] == [
        "322",
        "5331",
    ]


def test_an_appendix_citation_seeds_a_section_list_like_any_other() -> None:
    """ "46 app USC 808, 839" published 808 alone and dropped 839.

    Only ``_USC_STANDARD`` matches seeded the section-list walk, so a citation
    that named a title's APPENDIX got its first section and nothing else. Both
    of these are real: 46 App. U.S.C. 808 "Registration, enrollment, and
    licensing of vessels purchased, chartered, or leased" and 839 "Approvals
    by Secretary", the Shipping Act, 1916 as it stood in the appendix
    (uscode.house.gov, 1999 edition). So the gap dropped citations rather than
    declining ambiguous ones.

    15 distinct values, 37 source rows, measured 2026-08-22 over all 42,642
    distinct authority values: 45 rows gained, none lost, every one of them
    flagged ``usc_appendix``, across titles 46, 49 and 50 -- the three titles
    whose appendices this corpus cites.

    The flag is inherited on purpose. A title's appendix is a different body
    of law from the title proper -- which is why the appendix form is read
    first and fences the plain one off -- and half a list landing in the other
    one would merge two places the module exists to keep apart.
    """

    rows = parse_authority_citation("46 app USC 808, 839")
    assert [(r.usc_title, r.usc_section, r.usc_appendix) for r in rows] == [
        (46, "808", True),
        (46, "839", True),
    ]
    # Every spelling of the marker seeds the same walk, on either side of the
    # code name, and a subsection parenthetical inside the list is stepped over
    # exactly as it is in a plain one.
    for text, expected in (
        ("46 USC app 841a, 876", ["841a", "876"]),
        ("49 U.S.C. App. 13, 15 (1988)", ["13", "15"]),
        ("46 app USC 1101, 1114(b), 1122(d), 1241", ["1101", "1114", "1122", "1241"]),
        ("50 U.S.C. app. 2061 to 2170, 2171, and 2172", ["2061", "2171", "2172"]),
    ):
        rows = parse_authority_citation(text)
        assert [r.usc_section for r in rows] == expected, text
        assert all(r.usc_appendix for r in rows), text
    # The list still stops where every list stops: at another citation's head,
    # and at a comma that belongs to an act's name.
    assert [r.usc_section for r in parse_authority_citation("46 app USC 808, 839, Shipping Act, 1916")] == [
        "808",
        "839",
    ]
    # And a plain citation beside an appendix one keeps its own list, with its
    # own flag: the seeds are walked in document order, each window stopping at
    # the next seed. The heads publish before the tails because the families
    # are read in a fixed order and the list walk runs last -- that order is
    # the artifact's ``ordinal``, so it is pinned here rather than changed.
    mixed = parse_authority_citation("46 app USC 808, 839 and 46 USC 3703, 3704")
    assert [(r.usc_section, r.usc_appendix) for r in mixed] == [
        ("808", True),
        ("3703", False),
        ("839", True),
        ("3704", False),
    ]


def test_an_administrative_order_list_stops_where_the_register_begins() -> None:
    """ "Secretary's Orders 4-75 and 14-75" published 4-75 and dropped 14-75.

    The family had no list expansion, so a plural label listed in vain. Both
    are real and distinct Department of Labor orders -- 4-75 "Manpower
    Programs" (40 FR 18515) and 14-75 of November 12, 1975, which reorganized
    the Manpower Administration into the Employment and Training
    Administration; the Register cites "Order No. 14-75" in 9 documents and
    "Order 4-75" in 4 (federalregister.gov API, 2026-08-22).

    3 distinct values, 28 source rows, measured 2026-08-22 over all 42,642
    distinct authority values: the two DOL orders, Interior's Secretarial
    Orders 3299 and 3302 (13 and 1 Register documents respectively), and DHS
    Security Delegations 0170.1 and 5110 (5110 in 2 Register documents).

    Nothing else moved, and that is the point of the lookahead: this family's
    commonest neighbour is a Federal Register locator, and a list that ran on
    would harvest its VOLUME. Every singular-label value in the corpus is
    "Order N, <volume> FR <page>" and stops at the FR.

    The number carries its own right-hand boundary, which is what makes the
    lookahead work at all. Without it ``\\d+`` backtracked out from under the
    guard: "Secretary's Order No. 3-81, 46 FR 31117" read "4" as a listed
    order and offered "6 FR 31117" to the lookahead, which approved it. That
    number appears nowhere in the string.
    """

    for text, expected in (
        ("Secretary's Orders 4-75 and 14-75", ["4-75", "14-75"]),
        ("Secretarial Orders 3299 and 3302 (reorganization of MMS)", ["3299", "3302"]),
        ("Security Delegation Nos. 0170.1 and 5110, Revision 01", ["0170.1", "5110"]),
    ):
        rows = [r for r in parse_authority_citation(text) if r.authority_type == "administrative_order"]
        assert [r.admin_order_number for r in rows] == expected, text
        assert len({r.admin_order_kind for r in rows}) == 1, f"{text}: one label names both orders"

    # A Register locator behind the comma is never a listed order, in either
    # the backtracking shape or the plain one.
    for text in (
        "Secretary's Order No. 3-81, 46 FR 31117",
        "Secretary's Order 3-2007, 72 FR 15907",
        "Secretary of Labor Order 1-2012 and 29 CFR 1911",
        "Secretary's Order, 6-2010, 75 FR 66268-01 (Oct. 27, 2010)",
        "DOE Delegation Order No. 0204-112, 49 FR 6684 (February 22, 1984)",
    ):
        numbers = [
            r.admin_order_number for r in parse_authority_citation(text) if r.authority_type == "administrative_order"
        ]
        assert len(numbers) == 1, f"{text}: the Register volume is not a second order ({numbers})"
        assert numbers[0] in text.replace(" ", ""), f"{text}: {numbers[0]} is not in the string"


def test_a_lettered_statutes_range_carries_its_end_leaf() -> None:
    """ "114 Stat. 2763A-326 to 2763A-328" recorded 2763A-326 and dropped the rest.

    The reader consumed the end leaf and carried nothing, because there is no
    second page column -- and the only trace was a "partial" status, which
    every multi-citation value also carries and which therefore says nothing
    about which endpoint went missing. Silent loss, exactly.

    25 distinct values, 194 source rows, measured 2026-08-22 over all 42,642
    distinct authority values. Every one is Pub. L. 106-554 sec. 1505 at
    114 Stat. 2763A-326 to 2763A-328, written eleven ways.

    The end is carried in ``statute_page_text`` as a RANGE STRING spelled with
    " to ". A page's identity in this column is already a string, and a range
    of pages is not a page: a consumer keying on one can tell them apart by
    looking, which it could not do if the endpoints were fused into a longer
    compound.

    The publisher spells the end three ways and the pattern must try the FULL
    one first. Reading "to 2763A-328" without that alternative harvests
    "2763" -- the first four digits of the next page's own base -- and
    publishes a range ending at a page the string never named. That defect
    only became visible once the end leaf was carried, which is the argument
    for carrying it.
    """

    spellings = {
        "sec 1505 of PL 106-554, 114 Stat 2763A-326 to 2763A-328",
        "sec. 1505 of Pub. L. 106-554, 114 Stat. 2763A-326 to -328",
        "sec. 1505 of Pub. L. 106-554, 114 Stat. 2763A-326 to 328",
        "sec 1505 of PL 106-554, 114 Stat 2763A-326-328",
        "114 Stat 2763a-326 to -328",
    }
    for text in spellings:
        pages = [r.statute_page_text for r in parse_authority_citation(text) if r.statute_page_text]
        assert pages == ["2763A-326 to 2763A-328"], text
    # A whole value that IS the range is now covered, so it stops being
    # partial over a drop that no longer happens.
    whole = parse_authority_citation("114 Stat. 2763A, 326 to 328")[0]
    assert (whole.statute_page_text, whole.parse_status) == ("2763A-326 to 2763A-328", "ok")
    # A single page is still a single page, and the int column still stays
    # NULL because the compound is the identity.
    single = parse_authority_citation("113 Stat 1501A-293")[0]
    assert (single.statute_page_text, single.statute_page) == ("1501A-293", None)
    # Fail-closed, the U.S.C. ordering rule's own posture: an end that does not
    # follow its start, or that names a different base, is not a range.
    for text in ("114 Stat 2763A-326 to 320", "114 Stat 2763A-326 to 1501A-328"):
        row = parse_authority_citation(text)[0]
        assert row.statute_page_text == "2763A-326", text
        assert row.parse_status == "partial", f"{text}: a declined tail stays visible"


def test_a_bare_volume_us_page_is_a_code_citation_with_a_lost_c() -> None:
    """ "40 U.S. 550" was published as a Supreme Court case that does not exist.

    The whole family is one missing C. The PERIODS decided whether the corpus
    got a loud refusal or a silent lie: "42 US 2201" and eight siblings refuse
    as other/failed, while "40 U.S. 550" and "43 U.S. 1763" matched the case
    reporter and were typed ``case_citation``, status "ok", flagged by
    nothing. 3 distinct values, 9 source rows, measured 2026-08-22 -- the two
    silent ones and "7 U.S. 6g", which refused loudly. One operator answers
    all three, because the damage is one damage and only the reading it
    competed with differed.

    The case reading is refused by US citation practice: a case citation names
    its case or its year. All 20 of the other case values in this corpus carry
    a party name, a year, or both; these carry neither, so what they name is a
    decision nobody can identify.

    Exactly one survivor, and it is the publisher's own answer -- the
    authority note of the rule's own CFR part, with each record's siblings
    corroborating it a second time (eCFR, fetched 2026-08-22):

    * RIN 0991-AC14 revises 45 CFR part 12a -- "Authority: 42 U.S.C. 11411;
      40 U.S.C. 550." The record's other authority is "42 U.S.C. 11411".
    * RIN 1004-AF32 revises 43 CFR part 2800 -- "Authority: 43 U.S.C. 1733,
      1740, 1763, 1764, and 3003." The record also writes 1733 and 1740.
    * RIN 3038-AE36 revises 17 CFR 1.31 -- part 1's note runs "7 U.S.C. 1a, 2,
      5, 6, 6a, 6b, ... 6f, 6g, 6h, ...", and the record writes six further
      title 7 sections beside it, every one spelled "U.S.C.".
    """

    for text, title, section in (("40 U.S. 550", 40, "550"), ("43 U.S. 1763", 43, "1763"), ("7 U.S. 6g", 7, "6g")):
        rows = parse_authority_citation(text)
        assert [(r.authority_type, r.usc_title, r.usc_section) for r in rows] == [("usc", title, section)]
        assert rows[0].parse_status == "ok", text
        assert not any(r.case_volume for r in rows), f"{text}: no case is being named here"

    # A real case citation is untouched, because it carries what a case
    # citation carries -- and the whole-value anchor means this operator never
    # even sees one.
    for text in (
        "Touhy v. Ragen, 340 U.S. 462 (1951)",
        "Lau v. Nichols, 414 U.S. 563 (1974)",
        "Trinity Lutheran Church of Columbia, Inc. v. Comer, 582 U.S. 449 (2017)",
    ):
        row = parse_authority_citation(text)[0]
        assert row.authority_type == "case_citation", text

    # The periodless spellings stay refused: each needs its own record-level
    # corroboration, and a loud refusal is honest where a silent case citation
    # was not. 8 values / 10 rows in the corpus.
    for text in ("42 US 2201", "15 US 1392", "30 US 820", "49 US 44719", "50 US 2401 et seq"):
        assert [r.authority_type for r in parse_authority_citation(text)] == ["other"], text


def test_plural_part_ranges_keep_endpoints_and_plural_compounds_keep_names() -> None:
    """The old title-only range refusal is replaced by explicit endpoints.

    Real Agenda forms previously named in this test remain controls. The
    publisher XML additionally proves that plural title-41 lists contain
    compound part names; plural does not mean split each hyphenated token.
    """
    for text, title, start, end in (
        ("16 CFR pts. 0-4", 16, "0", "4"),
        ("16 CFR parts 0-4", 16, "0", "4"),
        ("40 CFR parts 1500-1508", 40, "1500", "1508"),
        ("20 CFR parts 660 - 672", 20, "660", "672"),
        ("41 CFR parts 102-33 to 102-42", 41, "102-33", "102-42"),
        ("31 CFR Parts 202-391", 31, "202", "391"),
        ("46 CFR Parts 53 to 54", 46, "53", "54"),
    ):
        (ranged,) = parse_cfr_citations(text)
        assert isinstance(ranged, CfrCitationRange)
        assert [(c.cfr_title, c.cfr_part) for c in (ranged.start, ranged.end)] == [(title, start), (title, end)]
    assert _parts("7 C.F.R. pts. 300, 319") == ["300", "319"]
    assert _parts("12 CFR pt. 1081 subpart E") == ["1081"]
    assert _parts("41 CFR 60-1") == ["60-1"]
    assert _parts("41 CFR part 102-117") == ["102-117"]
    assert _parts("40 CFR parts 60, 61", list_expansion="always") == ["60", "61"]


#: The lost-hyphen family, and the REFUSAL to repair it. Each entry is
#: (token as the publisher wrote it, U.S.C. title, source rows), measured
#: 2026-08-22 over all 42,642 distinct authority values: a section-shaped
#: token whose letters are not one letter repeated, so the section grammar
#: cannot read it whole, and which is neither a fused code label ("21USC"),
#: a fused word ("7401et", "6921through") nor a fused act abbreviation
#: ("1311CWA") -- the three families the module already names.
LOST_HYPHEN_SPECIMENS = (
    ("300ea", 42, 25),
    ("80bll", 15, 17),
    ("78cl", 17, 8),
    ("1437cA", 42, 5),
    ("717io", 15, 4),
    ("78cn", 15, 3),
    ("78jA", 15, 3),
    ("6bi", 7, 3),
    ("742aj", 16, 2),
    ("77fc", 15, 1),
    ("77fs", 15, 1),
    ("78dll", 15, 1),
    ("668ddU", 16, 1),
    ("136fFIFRA", 7, 1),
)


def test_a_lost_hyphen_is_refused_because_the_pinned_oracle_cannot_adjudicate_it() -> None:
    """ "80bll(a)" is 15 U.S.C. 80b-11(a), and this module will not say so.

    14 distinct tokens, 75 source rows. The commonest is the SEC's own
    Advisers Act authority: "15 USC 80b-4, 80b-6(4), 80bll(a), 80b-3(c)(1)"
    (17 rows), where three siblings read cleanly and the fourth -- 80b-11(a),
    "Rules, regulations, and orders of Commission"
    (uscode.house.gov, title 15 section 80b-11) -- is dropped entirely.

    A repair needs a named operator against a PINNED ORACLE with exactly one
    survivor. The operator is nameable ("one lost hyphen", plus the digit-one
    typed as the letter l). The oracle is what refuses, and it refuses in the
    worst possible way rather than by staying silent:

    ``output/usc-act-index-2026-08-02`` and
    ``output/usc-source-credit-index-2026-08-02`` hold 13,274 (title, section)
    pairs, drawn from 24 ACTS. They are an act index, not a roster of the
    Code, so **non-membership is not evidence of non-existence** -- and
    membership is sparse and arbitrary with respect to this question. Run
    exactly-one-survivor against them and 3 of the 14 tokens produce a single
    survivor, of which at least one is provably WRONG: the oracle does not
    hold 15 U.S.C. 80b-11 but does hold 15 U.S.C. 80b-1, so the test would
    pick 80b-1 -- a real section, about the Act's findings, that this citation
    does not mean -- and pick it with full confidence.

    That is the finding worth keeping. A partial roster does not merely fail
    to adjudicate; it manufactures a wrong adjudication that looks adjudicated.
    Whoever closes this gap needs a section-existence oracle over the whole
    Code, and this test is what should fail when they bring one.

    Nothing vanishes meanwhile: the digits before the letters are still read,
    the row is partial, and the letters stay in the authority text where a
    consumer studying publisher damage can see them.
    """

    advisers = "15 USC 80b-4, 80b-6(4), 80bll(a), 80b-3(c)(1)"
    sections = [row.usc_section for row in parse_authority_citation(advisers)]
    assert sections == ["80b-4", "80b-6", "80b-3"], "the damaged token is refused, not guessed"
    assert "80b-1" not in sections, "and the oracle's single survivor is not minted either"
    assert all(row.parse_status == "partial" for row in parse_authority_citation(advisers))

    # Every specimen: the whole token is never published as a section, and the
    # digits in front of it still are wherever the reader can reach them.
    for token, _title, _rows in LOST_HYPHEN_SPECIMENS:
        rows = parse_authority_citation(f"{_title} U.S.C. {token}")
        assert all((row.usc_section or "") != token.lower() for row in rows), token
        digits = re.match(r"\d+", token).group(0)
        assert any((row.usc_section or "").startswith(digits) for row in rows), token


#: Every (title, padded, unpadded) the pinned Agenda table states, measured
#: 2026-08-22: 943 rows across 101 distinct authority values wear a pad on the
#: whole token, 941 of them in title 26, and one further value wears one on a
#: compound's leaf. Listed rather than counted because the CLAIM is per pair —
#: the padded form names nothing and the stripped one names law.
ZERO_PADDED_SECTIONS = (
    (26, "0882", "882"),
    (26, "0956", "956"),
    (26, "0884", "884"),
    (26, "0367", "367"),
    (26, "0954", "954"),
    (26, "0892", "892"),
    (26, "0987", "987"),
    (26, "0989", "989"),
    (26, "0864", "864"),
    (26, "0904", "904"),
    (40, "01", "1"),
    (15, "80a-06", "80a-6"),
)


def test_a_zero_padded_section_is_the_section_it_pads() -> None:
    """ "26 U.S.C. 0989(c)" published section "0989", and §0989 is not law.

    The pad is the filer's own convention, not the Code's: RIN 1545-BL12 writes
    "26 USC 0987" and "26 USC 0989(c)" — the §987/§989 foreign-currency pair —
    beside an unpadded "26 USC 7805" in the same record. The grammar carried
    the pad straight into the identity column, where it is join-breaking and
    silent: 943 rows / 101 distinct values / 48 (title, section) pairs, 941 of
    the rows in title 26, and nothing anywhere said so.

    This is :func:`_canonical_part`'s rule one column over — the section is a
    JOIN KEY, and "0989" must meet "989" — and it costs the stated text
    nothing, because the table carries ``authority_text`` beside the identity.

    The precision claim is measured against the pinned oracle rather than
    asserted: no U.S.C. section is legitimately zero-padded, all 49 distinct
    stripped pairs name a section the oracle has seen, and not one padded pair
    does. See :func:`test_the_pinned_oracle_knows_no_zero_padded_section`.
    """

    for title, padded, unpadded in ZERO_PADDED_SECTIONS:
        rows = parse_authority_citation(f"{title} U.S.C. {padded}")
        assert [(r.usc_title, r.usc_section) for r in rows] == [(title, unpadded)], padded
    # The pad is stripped wherever a reader finds one, not only in the
    # abbreviated spelling.
    assert parse_authority_citation("26 U.S.C. 0989(c)")[0].usc_section == "989"
    assert parse_authority_citation("section 0989 of title 26")[0].usc_section == "989"
    assert parse_authority_citation("26 USC 0987, 0989")[-1].usc_section == "989"
    # A zero the section OWNS is untouched, at either end of the token.
    for text, section in (
        ("26 U.S.C. 1002", "1002"),
        ("42 U.S.C. 300j-9", "300j-9"),
        ("42 U.S.C. 1395w-4", "1395w-4"),
        ("49 U.S.C. 40120", "40120"),
    ):
        assert parse_authority_citation(text)[0].usc_section == section, text
    # NAMED REFUSAL: a pad after a hyphen is read only where the stem ends in a
    # LETTER, because only there is the span reading unavailable. An
    # abbreviated span drops a stem's repeated leading DIGITS, so
    # "49 USC 20701-03" is §§20701-20703 and NOT a padded §20701-3 — 15 values
    # / 33 rows in titles 49 and 38 read that way. This rule hands them to the
    # span rule intact, and :func:`_abbreviated_span` decides them there.
    for text, section, end in (
        ("49 USC 20701-03", "20701", "20703"),
        ("49 USC 32901-02", "32901", "32902"),
        ("38 USC 2307-08", "2307", "2308"),
    ):
        row = parse_authority_citation(text)[0]
        assert (row.usc_section, row.usc_section_end) == (section, end), text


def test_a_treaty_series_outranks_the_code_label_it_wears() -> None:
    """ "27 U.S.C. 1087" is 27 U.S.T. 1087 — CITES — and read as the Code.

    3 distinct values, 38 source rows, measured 2026-08-22. One of them NAMES
    the Convention and still yielded a Code citation, which is the sharpest
    specimen the campaign found: ``_USC_STANDARD`` wins on the label, and
    ``_TREATY_UST`` never sees the value.

    Exactly one survivor, and both halves are measured rather than argued.
    The Code reading is impossible: title 27 is Intoxicating Liquors, its 39
    enumerated sections top out at 219a and its printed ranges end "221 to
    228", in every edition 1994-2026 — so no 27 U.S.C. 1087 exists to mean.
    The treaty reading is real and the corpus states it: three further values
    / 12 rows write the same volume and page with the T intact.

    The PAIR is the fence, not the anchor, which is why this repair alone may
    carry a prefix — no prose donates "27 USC 1087", and the prefix the corpus
    writes is the instrument's own name.
    """

    for text in ("27 U.S.C. 1087", "27 USC 1087", "27 usc 1087"):
        rows = parse_authority_citation(text)
        assert [(r.authority_type, r.treaty_series, r.treaty_volume, r.treaty_page) for r in rows] == [
            ("treaty", "UST", 27, 1087)
        ], text
        assert rows[0].parse_status == "ok", text
    # The value that names the Convention now reads as ONE citation, the same
    # one its undamaged siblings read as — where before it published a
    # series-less instrument-name row beside a phantom Code section.
    cites = (
        "Convention on International Trade in Endangered Species of Wild Fauna and Flora (March 3, 1973), 27 USC 1087"
    )
    sibling = (
        "27 UST 1087, Convention on International Trade in Endangered Species of Wild Fauna and Flora (March 3, 1973)"
    )
    assert [
        (r.authority_type, r.treaty_series, r.treaty_volume, r.treaty_page) for r in parse_authority_citation(cites)
    ] == [
        (r.authority_type, r.treaty_series, r.treaty_volume, r.treaty_page) for r in parse_authority_citation(sibling)
    ]
    # The pinned pair is the whole of the claim. Title 27's real sections, the
    # same section under a title that HAS one, and the same page under the
    # series label are all untouched.
    for text, kind, title, section in (
        ("27 USC 205", "usc", 27, "205"),
        ("27 U.S.C. 219a", "usc", 27, "219a"),
        ("20 USC 1087", "usc", 20, "1087"),
        ("20 U.S.C. 1087aa", "usc", 20, "1087aa"),
    ):
        rows = parse_authority_citation(text)
        assert [(r.authority_type, r.usc_title, r.usc_section) for r in rows] == [(kind, title, section)], text


#: The six real sections whose compound leaf ascends within 99 of its stem, so
#: no rule written on the characters alone can tell them from an abbreviated
#: span. Found by running the span predicate over the pinned oracle's 282 real
#: all-digit hyphenated sections; measured INERT on this corpus (zero of the
#: 42,642 distinct authority values names any of them).
SPANS_THAT_ARE_REALLY_SECTIONS = (
    (42, "5714-21"),
    (42, "5714-22"),
    (42, "5714-23"),
    (42, "5714-24"),
    (42, "5714-25"),
    (42, "5714-41"),
)

#: (title, as published, first section, last section, source rows). Every one
#: is a token the pinned artifact carries in its section IDENTITY column and
#: the oracle says is not a section.
ABBREVIATED_SPANS = (
    (31, "3801-12", "3801", "3812", 19),
    (29, "1029-30", "1029", "1030", 17),
    (29, "1023-24", "1023", "1024", 16),
    (42, "3601-19", "3601", "3619", 13),
    (28, "2671-80", "2671", "2680", 7),
    (12, "1861-67", "1861", "1867", 4),
    (49, "20137-38", "20137", "20138", 4),
    (49, "20701-03", "20701", "20703", 3),
    (38, "1804-805", "1804", "1805", 3),
)


def test_an_abbreviated_span_is_two_sections_not_one_name() -> None:
    """ "2671-80" is §§2671-2680 (the FTCA), and it was published as a name.

    GPO and Bluebook 3.2(a) abbreviate an inclusive span by dropping the
    repeated leading digits of its second endpoint. The grammar kept the token
    whole — a documented fail-closed choice — and the token then landed in the
    section IDENTITY column, indistinguishable from a real compound name like
    "1395w-4". 264 rows over 68 distinct (title, token) pairs and 79 distinct
    authority values, measured 2026-08-22 over the pinned Agenda table.

    The oracle is what reopened the question, and it answers both halves:
    **zero of the 68 tokens name a real section as written**, and **62 of them
    expand to a span whose BOTH endpoints are real** (246 of the 264 rows),
    against the pairs pinned in
    ``research/evidence/usc-section-oracle-2026-08-24``. So the identity
    column carries 264 rows of a name that is not law, and the span it becomes
    is law at both ends in 62 of 68.

    The other SIX keep an endpoint the oracle does not know, and they are named
    in :data:`PHANTOM_SPANS`. They are no worse off as a span than as a token
    naming nothing, and they are not repaired here — but they are no longer
    silent: every expansion carries ``usc_section_span_rule`` and none of them
    is typed "ok". See
    :func:`test_an_expanded_span_says_it_was_expanded_and_is_never_ok`.
    """

    for title, published, first, last, _rows in ABBREVIATED_SPANS:
        row = parse_authority_citation(f"{title} U.S.C. {published}")[0]
        assert (row.usc_section, row.usc_section_end) == (first, last), published
        # NOT "ok": the endpoints are read, the sections BETWEEN them are
        # inferred, and this module cannot check the inference.
        assert row.parse_status == "partial", published
        assert row.usc_section_span_rule == citation_grammar.USC_SPAN_ABBREVIATED, published
    # The list walk expands its members the same way, and a subsection tail
    # still leaves the row partial rather than "ok".
    listed = parse_authority_citation("29 U.S.C. 1021, 1023-24, 1026-27, 1029-30, and 1135")
    assert [(c.usc_section, c.usc_section_end) for c in listed] == [
        ("1021", None),
        ("1023", "1024"),
        ("1026", "1027"),
        ("1029", "1030"),
        ("1135", None),
    ]


#: (title, published token, first, last, members the span claims, members the
#: oracle knows, source rows). Every one is an expansion whose ENDPOINT the
#: oracle does not know, so the span it asserts is not law.
#:
#: SIX, not five. The five that :func:`_abbreviated_span` named were carried
#: from a docstring rather than recounted, and "42 USC 105-33" — 29 sections
#: claimed, 6 of them law — was never in the list. That is the whole argument
#: for :func:`test_an_expanded_span_says_it_was_expanded_and_is_never_ok`
#: recomputing the population instead of restating it.
#:
#: NINE since 2026-08-24, and the three arrivals are the price of reading a
#: SPELLED abbreviation ("1817 to 19") the way the hyphenated one was always
#: read. Two are the publisher's own stutter — "7 USC 77701 to 7772" is 7701
#: typed twice and claims 72 sections of which none is law, "49 USC 440113 to
#: 40114" is 40113 the same way — and one is a filer overreaching a real Act:
#: "42 USC 3601 to 20" is the Fair Housing Act, whose sections stop at 3619.
#: **All nine are refused downstream** by the builder's endpoint gate
#: (``_refuse_unprintable_span_ends``), which is the reader-with-an-oracle
#: this module's own docstring asks for; the grammar still reads them, and
#: this table is what it reads.
PHANTOM_SPANS = (
    (16, "4601-31", "4601", "4631", 31, 8, 4),
    (16, "4602-31", "4602", "4631", 30, 7, 3),
    (42, "105-33", "105", "133", 29, 6, 3),
    (26, "1502-13", "1502", "1513", 12, 4, 4),
    (42, "3007-11", "3007", "3011", 5, 1, 2),
    (8, "81611-1613", "81611", "81613", 3, 0, 2),
    (7, "77701 to 7772", "77701", "77772", 72, 0, 3),
    (42, "3601 to 20", "3601", "3620", 20, 19, 2),
    (49, "440113 to 40114", "440113", "440114", 2, 0, 1),
)

#: The two spans an ENDPOINT test would pass and a consumer would still be
#: wrong about: both endpoints are law, the interior is sparse. 16 U.S.C.
#: 1801-81 is Magnuson-Stevens, whose sections are not contiguous, and it is
#: the largest miss of all — 45 of the 81 sections claimed are not law, more
#: than any phantom span costs.
#: The third arrived with the spelled abbreviation: "16 USC 3101 to 26" is
#: ANILCA, whose 26 claimed sections are 19 law. Its endpoints are both law, so
#: the builder's endpoint gate does NOT refuse it -- which is the same posture
#: Magnuson-Stevens has had all along, and the reason that gate is stated as an
#: endpoint test rather than sold as a span test.
SPANS_WHOSE_INTERIOR_IS_SPARSE = (
    (16, "1801-81", "1801", "1881", 81, 36, 2),
    (42, "12101-13", "12101", "12113", 13, 6, 13),
    (16, "3101 to 26", "3101", "3126", 26, 19, 6),
)


def test_an_expanded_span_says_it_was_expanded_and_is_never_ok() -> None:
    """An expansion is an inference, and the output said nothing about that.

    "2671-80" and "7401 to 7671q" land in the same two columns. One was read
    off the characters; the other is this module asserting sections the
    publisher never wrote. A consumer that WALKS a span gets a claim over every
    member, and for 16 U.S.C. 4601-31 that is 31 sections of which 23 are not
    law — typed "ok", with nothing anywhere to tell it from a stated range.

    Two things now say so. ``usc_section_span_rule`` names which rule answered,
    and no expansion is typed "ok" — a consumer filtering on status never walks
    one by accident.

    Why blanket rather than "ok unless the oracle rejects an endpoint": the
    oracle is out of reach here (``usc_section_oracle`` imports this module, so
    this module cannot import it), AND an endpoint test would not be enough if
    it were. :data:`SPANS_WHOSE_INTERIOR_IS_SPARSE` passes both endpoints and
    still claims 45 sections of Magnuson-Stevens that are not law — a bigger
    miss than any of the six phantoms.
    """

    for title, published, first, last, *_ in PHANTOM_SPANS + SPANS_WHOSE_INTERIOR_IS_SPARSE:
        row = parse_authority_citation(f"{title} U.S.C. {published}")[0]
        assert (row.usc_section, row.usc_section_end) == (first, last), published
        assert row.usc_section_span_rule == citation_grammar.USC_SPAN_ABBREVIATED, published
        assert row.parse_status == "partial", published
    # A STATED span is the other value, and it keeps "ok": the publisher wrote
    # both endpoints and this module read them.
    for text, first, last in (
        ("42 U.S.C. 7401-7671q", "7401", "7671q"),
        ("16 U.S.C. 1531 to 1544", "1531", "1544"),
    ):
        row = parse_authority_citation(text)[0]
        assert (row.usc_section, row.usc_section_end) == (first, last), text
        assert row.usc_section_span_rule == citation_grammar.USC_SPAN_STATED, text
        assert row.parse_status == "ok", text
    # No span, no rule -- the column is a statement about a span and stays NULL
    # where there is none, including on the tokens the span rule declines.
    for text in ("42 U.S.C. 7401", "42 U.S.C. 1395w-4", "15 U.S.C. 80a-06", "50 U.S.C. 4801-4582"):
        assert parse_authority_citation(text)[0].usc_section_span_rule is None, text


def test_the_span_guards_are_three_and_each_refuses_something_real() -> None:
    """Each guard was bought by a real section the others would have eaten.

    * The TWO-DIGIT leaf: 251 of the 282 real all-digit hyphenated sections in
      the pinned oracle have a one-digit leaf, and every one of them — 42
      U.S.C. 288-1…288-6, 7 U.S.C. 1358-1, 26 U.S.C. 460-6 — would read as a
      span without it.
    * The leaf SHORTER than the stem: a pair that repeats nothing abbreviates
      nothing, which is what keeps "4801-4582" and "7671-7671" whole.
    * The gap inside :data:`_ABBREVIATED_SPAN_MAX_GAP`: ascending alone leaves
      "201701-20702" reading as a 19,001-section span, and Bluebook 3.2(a)
      keeps the last two digits, so a real abbreviation cannot reach 100.

    And the hazard the guards do NOT cover, named rather than hidden: six real
    sections survive all three. Nothing in the characters tells 42 U.S.C.
    5714-21 from 28 U.S.C. 2671-80, and this module holds no section-existence
    oracle to ask. They are measured inert on this corpus; a reader who
    acquires such an oracle should fence them there.
    """

    for text in (
        "42 U.S.C. 288-1",
        "42 U.S.C. 288-6",
        "7 U.S.C. 1358-1",
        "26 U.S.C. 460-6",
        "50 U.S.C. 4801-4582",
        "42 U.S.C. 7671-7671",
        "49 U.S.C. 201701-20702",
        "12 U.S.C. 1831p-1",
        "42 U.S.C. 1395w-4",
        "15 U.S.C. 80a-06",
    ):
        row = parse_authority_citation(text)[0]
        assert row.usc_section_end is None, text
        assert "-" in row.usc_section, f"{text}: the token keeps its own hyphen"
    # The stated hazard, asserted so it cannot be forgotten: these six DO read
    # as spans, and the claim about them is only that the corpus never says
    # them.
    for title, section in SPANS_THAT_ARE_REALLY_SECTIONS:
        assert parse_authority_citation(f"{title} U.S.C. {section}")[0].usc_section_end is not None


#: The bare 0-for-o spellings this module REFUSES, with the section each would
#: become and its source rows. Every one is absent from the pinned oracle and
#: every o-form is real, so an oracle-carrying reader could settle all five —
#: but the shape alone cannot, because a bare token ending in zero is usually
#: a section (15 U.S.C. 780 is real, and so are 7,000 others).
BARE_O_FOR_ZERO_REFUSED = (
    (26, "450", "45o", 14),
    (7, "4990", "499o", 8),
    (42, "76510", "7651o", 4),
    (16, "8240", "824o", 1),
    (15, "16930", "1693o", 1),
)


def test_the_o_for_zero_homoglyph_damages_a_section_too() -> None:
    """ "15 USC 780-5(b)" is 15 U.S.C. 78o-5(b), and the mirror had no reader.

    ``letter-o-for-zero-in-usc-title`` reads "3o USC 1201" as 30 U.S.C. 1201;
    the identical homoglyph inside the SECTION had no operator and no flag. 10
    distinct values, 33 rows, measured 2026-08-22.

    Exactly one survivor, pinned twice. "15 U.S.C. 780-N" is absent from the
    oracle for every N the corpus states, while the Exchange Act's §15O runs
    78o-1 through 78o-11 and every one of them is real. And six of the eight
    RINs that file the damaged spelling also file the clean one, several at the
    same section: RIN 1505-AA70 writes both "15 USC 780-5(b)" and
    "15 USC 78o-5(b)".

    The BARE spelling is left alone, which is the near-miss worth recording:
    15 U.S.C. 780 is a real section ("Office of Private Grievances and
    Redress"), so only the compound is impossible.
    """

    for damaged, section in (
        ("15 USC 780-3", "78o-3"),
        ("15 USC 780-5", "78o-5"),
        ("15 USC 780-5(b)", "78o-5"),
        ("15 USC 780-5(f)", "78o-5"),
        ("15 U.S.C. 780-10", "78o-10"),
        ("15 U.S.C. 780-10(b)(6)", "78o-10"),
        ("15 USC 780-11", "78o-11"),
    ):
        rows = parse_authority_citation(damaged)
        assert [(r.usc_title, r.usc_section) for r in rows] == [(15, section)], damaged
    # The bare section, and the same shape under a title where the oracle says
    # the DIGIT is right: 16 U.S.C. 760-1…760-12 are real sections, and a rule
    # written on the shape would have rewritten them into nothing. 30 real
    # sections carry a compound stem ending in zero.
    for text, section in (
        ("15 U.S.C. 780", "780"),
        ("15 USC 7805", "7805"),
        ("16 U.S.C. 760-10", "760-10"),
        ("2 U.S.C. 60-1", "60-1"),
        ("8 U.S.C. 1440-1", "1440-1"),
        ("16 U.S.C. 470-1", "470-1"),
    ):
        assert parse_authority_citation(text)[0].usc_section == section, text
    # NAMED REFUSAL: the bare 0-for-o family, 28 rows. Each would need a
    # section-existence oracle at read time, which this module does not carry.
    for title, published, _becomes, _rows in BARE_O_FOR_ZERO_REFUSED:
        assert parse_authority_citation(f"{title} U.S.C. {published}")[0].usc_section == published


def test_a_cfr_authority_carries_the_section_it_names() -> None:
    """ "delegation of authority at 49 CFR 1.95" is not "49 CFR part 1".

    ``parse_cfr_citations`` has read the section since the CFR grammar
    existed, and :class:`AuthorityCitation` had nowhere to put it, so every
    consumer of an authority row got the part alone. That is not a misread —
    each citation delivered is correct — but it is the same harm: 309 distinct
    values / 4,126 rows arrive one unit coarser than they were written, and 22
    (title, part) pairs collapse more than one section into one citation.

    The worst is 49 CFR part 1, where 22 distinct DOT delegation sections —
    1.45, 1.46, 1.47, 1.48, 1.49, 1.50, 1.50a … — all arrive as one citation,
    followed by 5 CFR 2635 (11 sections), 33 CFR 6 (7), 7 CFR 2 (6), 28 CFR 0
    (5), 48 CFR 1 (4). Measured over the pinned Agenda table; the CFR reference
    table beside it has carried the column all along.

    The count is recomputed rather than quoted, by
    :func:`test_the_cfr_section_population_is_one_number_recomputed`, because
    this fact was carried by three different numbers.
    """

    for text, title, part, section in (
        ("delegation of authority at 49 CFR 1.95", 49, "1", "95"),
        ("49 CFR 1.50", 49, "1", "50"),
        ("49 CFR 1.50a", 49, "1", "50a"),
        ("5 CFR 2635.403", 5, "2635", "403"),
        ("28 CFR 0.75", 28, "0", "75"),
        # The two self-citations read a section after the dot too, and both
        # threw it away for want of a column.
        ("FAR 1.105-2", 48, "1", "105-2"),
        ("DFARS 201.3", 48, "201", "3"),
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "cfr"]
        assert [(r.cfr_title, r.cfr_part, r.cfr_section) for r in rows] == [(title, part, section)], text
    # A part-less or section-less citation still states exactly what it states.
    for text, title, part in (("40 CFR part 60", 40, "60"), ("3 CFR", 3, None)):
        row = next(r for r in parse_authority_citation(text) if r.authority_type == "cfr")
        assert (row.cfr_title, row.cfr_part, row.cfr_section) == (title, part, None), text


def test_a_delegations_paragraph_is_not_a_second_delegation() -> None:
    """ "DHS Delegation No. 0170.1(92)" minted a second identity for one instrument.

    The number capture treated a trailing "(92)" as a revision of the
    delegation, so the Coast Guard's single authority arrived under three
    names — 0170.1, 0170.1(75) and 0170.1(92) — and a consumer asking which
    rules rest on DHS Delegation 0170.1 missed 61 of them. 8 distinct values,
    61 rows, measured 2026-08-22.

    The corpus refutes the revision reading in its own words, at the same
    office and the same instrument: "DHS Delegation No. 0170.1, para (92)"
    (15 rows), "DHS Delegation 0170.1, paragraph 92" (9), "DHS Delegation No.
    0170.1, paragraph (92)(b)" (3), and "DHS Delegation No 0170.1 (92)(a),
    (92)(b)" (4) — which, being spaced, already read as 0170.1. The bare
    instrument is filed 350 times against 61 for the parenthesised spellings.

    The paragraph stays uncovered text, which keeps those rows partial and the
    characters visible: nothing is dropped, and no paragraph column is
    invented for a fact one office states four ways.
    """

    for text in (
        "DHS Delegation No. 0170.1(92)",
        "DHS Delegation No. 0170.1(75)",
        "DHS Delegation No. 0170.1(92)(b)",
        "DHS Delegation No 0170.1(92)",
        "Department of Homeland Security Delegation No. 0170.1(92)(a), (92)(b)",
        "DHS Delegation No. 0170.1, para (92)",
        "DHS Delegation No. 0170.1",
    ):
        rows = parse_authority_citation(text)
        assert rows[0].admin_order_number == "0170.1", text
    # A LETTER suffix is still part of a number, and a dashed one still is.
    assert parse_authority_citation("Secretary's Order 4-75")[0].admin_order_number == "4-75"
    assert parse_authority_citation("Secretary of the Air Force Order 111.1")[0].admin_order_number == "111.1"
    # And the list tail is unharmed: its number spells the same shape, so a
    # widening in one would have been a silent divergence from the other.
    listed = parse_authority_citation("Secretary's Orders 4-75 and 14-75")
    assert [row.admin_order_number for row in listed] == ["4-75", "14-75"]
    assert parse_authority_citation("Secretary's Order No. 3-81, 46 FR 31117")[0].admin_order_number == "3-81"


def test_a_compilations_second_year_may_be_abbreviated() -> None:
    """ "3 CFR 1949-53 Comp." is the 1949-1953 volume, and it minted part 1949.

    The compilation grammar read a four-digit closing year only, so the
    volumes the National Archives titles "3 CFR, 1949-1953 Comp." went
    undiverted wherever a filer abbreviated the second endpoint the way any
    span's second endpoint is abbreviated — and ``_CFR_STANDARD`` then minted
    the volume's FIRST year as a CFR part. 4 values / 7 rows: "3 CFR 1949-53
    Comp., sec 2" (part 1949), "3 CFR 1954-58, Comp, p. 218" (1954),
    "as amended, 3 CFR 1971-75 Comp., p.586" (1971), and the same value with
    a Reorganization Plan in front of it.

    Two further shapes came with it. A doubled dash may be SPACED — after
    dash normalization "3 CFR 1966 - \\x961970, p 939" reads "1966 - -1970"
    (1 row) — and a closing year may simply be mis-keyed, where the word
    "Comp." itself proves the shape: "3 CFR, 1971-1075 Comp., p. 793" (2 rows)
    is the 1971-1975 volume, and refusing it cost the page as well as the
    volume. The typo is carried, never corrected.

    NAMED REFUSAL: "3 CFR 1981" (6 rows) stays a CFR part. A single Comp-less
    year states nothing that separates a compilation from a part — the rule
    this grammar has always held — and 1981 is the first ANNUAL volume, so no
    year range can prove its shape either. Settling it needs a 1980s CFR
    title-3 part roster this module does not carry.
    """

    for text, start, end, page in (
        ("3 CFR 1949-53 Comp., sec 2", "1949", "1953", None),
        ("3 CFR 1954-58, Comp, p. 218", "1954", "1958", "218"),
        ("as amended, 3 CFR 1971-75 Comp., p.586", "1971", "1975", "586"),
        ("3 CFR 1966 - \x961970, p 939", "1966", "1970", "939"),
        ("3 CFR, 1971-1075 Comp., p. 793", "1971", "1075", "793"),
        ("3 CFR, 1949-1953 Comp.", "1949", "1953", None),
        ("3 CFR, 1977 Comp., p. 123", "1977", None, "123"),
    ):
        assert parse_eo_compilation_locators(text) == (
            citation_grammar.EoCompilationLocator(compilation_start=start, compilation_end=end, page=page),
        ), text
        rows = parse_authority_citation(text)
        assert [r.authority_type for r in rows] == ["eo_compilation"], text
        assert rows[0].eo_compilation_start == start, text
    # The refusal, and the rule it rests on: one year and no "Comp." is a part.
    for text in ("3 CFR 1981", "3 CFR 1990"):
        assert parse_eo_compilation_locators(text) == ()
        assert [(r.authority_type, r.cfr_part) for r in parse_authority_citation(text)] == [("cfr", text[-4:])]


def test_three_further_spellings_of_the_volume_the_publisher_writes() -> None:
    """ "3 CFR 1950 Supp.", "3 CFR 1987, p. 235", "3 CFR 1987, 1987 Comp."

    Three shapes the locator could not read, all of them found in the 8,240
    pinned authority notes and none of them in any of the 42,677 authority
    values, so this widening is the notes' alone.

    THE VOLUME'S OWN WORD is "Supp." before 1949 and "Comp." after: the Office
    of the Federal Register titled the early Title 3 volumes as supplements,
    and E.O. 10096 is printed in "3 CFR, 1950 Supp." Reading only "Comp." left
    five notes minting CFR parts out of volume years -- 34 CFR 7 and 45 CFR 7
    (parts 1950, 1953, 1961), 8 CFR 1215 (1953), 19 CFR 200 and 29 CFR 1400
    (1965).

    A PAGE LABEL proves the shape where the word is missing, on the same terms
    a year range does. 12 CFR 602's note writes "52 FR 23781, 3 CFR 1987, p.
    235" and published part 1987. A BARE number after the year still proves
    nothing and is still refused: the label is the whole evidence.

    A REPEATED YEAR is the publisher writing the volume twice. 5 CFR 10000's
    note reads "E.O. 12600, 52 FR 23781, 3 CFR 1987, 1987 Comp., p. 235", and
    the first 1987 was the minted part. The first year is stepped over only
    where the second is a year the compilation word follows.
    """

    for text, start, page in (
        ("3 CFR 1950 Supp.", "1950", None),
        ("3 CFR, 1953 Supp. Interpret or apply sec. 215", "1953", None),
        ("3 CFR. 1950 Supp. and E.O. 10930", "1950", None),
        ("52 FR 23781, 3 CFR 1987, p. 235.", "1987", "235"),
        ("E.O. 12600, 52 FR 23781, 3 CFR 1987, 1987 Comp., p. 235", "1987", "235"),
    ):
        locators = parse_eo_compilation_locators(text)
        assert [(one.compilation_start, one.page) for one in locators] == [(start, page)], text
        assert start not in {row.cfr_part for row in parse_cfr_citations(text)}, text

    # THE REFUSALS THIS DOES NOT TOUCH, and the residue it leaves. A bare year
    # is still a part, with or without a page-less tail; and 5 CFR 10000's own
    # "; 3 CFR 235." -- the page written a second time as if it were a part --
    # stays a CFR citation, because settling it needs the 1980s title-3 part
    # roster this module deliberately does not carry.
    assert parse_eo_compilation_locators("sec. 7(b), 3 CFR, 1987") == ()
    residue = parse_authority_citation(
        "5 U.S.C. 552, as amended; E.O. 12600, 52 FR 23781, 3 CFR 1987, 1987 Comp., p. 235; 3 CFR 235."
    )
    assert [(row.cfr_title, row.cfr_part) for row in residue if row.authority_type == "cfr"] == [(3, "235")]
    assert [
        (row.eo_compilation_start, row.eo_compilation_page) for row in residue if row.authority_type == "eo_compilation"
    ] == [("1987", "235")]

    # THE ONE ROW IN THE SIBLING TABLE. The repeated-year shape is written in
    # the Agenda's CFR_LIST field too, once: RIN 3480-AA00's Fall 2015 filing
    # says "3 CFR 1987, 1987 Comp., Pub. L. 235", and the CFR reader minted
    # title 3 part 1987 TWICE out of it -- once per year. The locator now
    # excises the whole phrase, so the reference reads nothing and its row
    # survives carrying the filer's text and no identity, which is the posture
    # 22,158 other rows of that table already have. It is the only row this
    # unit moves outside the authority table: unified_agenda_cfr_references
    # goes 444,848 -> 444,847, and the commit that landed the unit said the
    # sibling tables were unchanged because it compared the wrong pair of
    # scratch builds.
    assert parse_cfr_citations("3 CFR 1987, 1987 Comp., Pub. L. 235") == ()
    assert parse_eo_compilation_locators("3 CFR 1987, 1987 Comp., Pub. L. 235") == (
        citation_grammar.EoCompilationLocator(compilation_start="1987", compilation_end=None, page=None),
    )

    # THE ONE PLACE THE TWO YEARS DIFFER, named because the rule carries the
    # publisher's word rather than NARA's. 2 CFR 2700's note writes "E.O. 12689
    # (3 CFR, 1989, 1986 Comp., p. 235)", and E.O. 12689 is printed in 3 CFR,
    # 1989 Comp., p. 235 -- the "1986" is copied down from the E.O. 12549 line
    # above it. The volume read is the one the word follows, which is the
    # publisher's own syntax and the same posture the mis-keyed closing year
    # takes ("1971-1075 Comp."). What it replaces is two fabricated sections of
    # title 31, 1989 and 1986, harvested behind "(31 U.S.C. 6101 note)".
    muddled = parse_authority_citation(
        "Sec. 2455, Pub. L. 103-355, 108 Stat. 3327 (31 U.S.C. 6101 note); "
        "E.O. 12549 (3 CFR, 1986 Comp., p. 189); E.O. 12689 (3 CFR, 1989, 1986 Comp., p. 235)"
    )
    assert [row.usc_section for row in muddled if row.authority_type == "usc"] == ["6101"]
    assert [
        (row.eo_compilation_start, row.eo_compilation_page) for row in muddled if row.authority_type == "eo_compilation"
    ] == [("1986", "189"), ("1986", "235")]


def test_a_treaty_or_reporter_volume_behind_a_comma_is_not_a_listed_section() -> None:
    """ "50 U.S.C. 403g; ... Touhy v. Ragen, 340 U.S. 462" published 50 U.S.C. 340.

    The Federal Register joined the "another citation ahead" family because a
    number cannot be a Register volume and a Code section at once. Four more
    families this module reads were still missing, and they locate their
    instrument the identical way: a treaty series by volume and page ("19
    U.S.T. 6223", "1870 U.N.T.S. 167") and a case reporter by volume and page
    ("340 U.S. 462", "141 F.3d 662", "142 S. Ct. 1987").

    Measured 2026-08-24 over all 42,677 authority values and all 8,240 notes:
    18 occurrences in the values and 14 in 10 notes, every one a case name or a
    treaty title with a U.S.C. citation in front of it. Nothing vanishes -- the
    treaty and reporter families read the citation the number really belongs to
    out of the same string, which is exactly what makes the section reading
    self-contradictory.
    """

    for text, families in (
        (
            (
                "8 U.S.C. 1101, Protocol Relating to the Status of Refugees, November 1, 1968, "
                "19 U.S.T. 6223 (TIAS) 6577"
            ),
            "treaty",
        ),
        (
            "50 U.S.C. 403g; United States ex rel. Touhy v. Ragen, 340 U.S. 462 (1951)",
            "case_citation",
        ),
        (
            (
                "16 U.S.C. 1531, Convention on International Trade in Endangered Species of Wild "
                "Fauna and Flora (March 3, 1973), 27 U.S.T. 1087"
            ),
            "treaty",
        ),
        ("5 U.S.C. 301, State of Michigan v United States, 141 F 3d 662 (6th Cir 1998)", "case_citation"),
        ("42 U.S.C. 2000bb, Carson v. Makin, 142 S. Ct. 1987 (2022)", "case_citation"),
    ):
        rows = parse_authority_citation(text)
        listed = [row.usc_section for row in rows if row.authority_type == "usc"]
        assert len(listed) == 1, (text, listed)
        assert families in {row.authority_type for row in rows}, text

    # PAIRED NEGATIVE. The guard is the LABEL and nothing else: a listed section
    # that happens to equal a reporter volume still lists, and so does one
    # followed by a word that merely starts the same way.
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 340, 141")] == [
        "1983",
        "340",
        "141",
    ]
    assert [row.usc_section for row in parse_authority_citation("42 U.S.C. 1983, 340 United States")] == [
        "1983",
        "340",
    ]


def test_a_stated_section_stops_where_the_next_word_begins() -> None:
    """ "sec 6002Omnibus Budget Reconciliation Act" stated a section "6002Omnibus".

    The statement reader's capture was ``[\\w.\\-]*``, which took whatever
    followed the digits — the same lost-space damage
    :data:`_USC_SECTION_TOKEN` already fences for the Code, at the one reader
    that had no fence. Its letters now obey the Code's own rule: a letter run
    is ONE LETTER REPEATED and carries its own right edge.

    Measured over all 1,974 distinct ``stated_section`` values the pinned
    table carries (28,321 rows), exactly four contain a run of two different
    letters, and all four are this damage: "6002Omnibus" (6 rows, 2 values),
    "123BBRA", "301as" and "501to" — 9 rows. Two further values never reached
    the table because the builder replaces a statement with a resolution:
    "Other sections of FDA Food Safety Modernization Act, as appropriate" and
    its lowercase twin stated a section named "of" (7 rows).
    """

    for text, section in (
        ("PL 103-66, sec 6002Omnibus Budget Reconciliation Act of 1993", "6002"),
        ("Sec 123BBRA 1999", "123"),
        ("sec 301as amended", "301"),
        ("sec 501to 505", "501"),
        ("Social Security Act, sec 1818A60(2)", "1818A"),
    ):
        assert citation_grammar.stated_section(text) == section, text
    assert citation_grammar.stated_section("Other sections of FDA Food Safety Modernization Act") is None
    # Acts number their sections every way there is, and none of it is damage.
    for text, section in (
        ("sec 205(c)", "205(c)"),
        ("section 4.14B", "4.14B"),
        ("sec 1860D-31", "1860D-31"),
        ("sec 1861(v)(1)(A)", "1861(v)(1)(A)"),
        ("sections 114(a)(3)", "114(a)(3)"),
        ("Pub. L. No 118-50 Sec N", "N"),
        ("sec 2000bb", "2000bb"),
        ("sec 77aaaa", "77aaaa"),
    ):
        assert citation_grammar.stated_section(text) == section, text


def test_a_cfr_part_carries_its_verdict_and_the_retyping_stays_refused() -> None:
    """The CFR reader judged the part and the authority reader dropped the verdict.

    ``parse_cfr_citations`` has always returned ``part_is_plausible``;
    :class:`AuthorityCitation` had no field for it, so ``parse_authority_citation``
    checked ``title_is_possible`` and discarded the other half. The identical
    string is therefore judged in one pinned table and unjudged in the other:
    "42 CFR 412106" carries ``cfr_part_is_plausible = false`` in the CFR
    reference table (6 rows) and arrived in the authority table with nothing
    said. Measured 2026-08-22: 584 distinct authority citations over 578
    values and 6,574 rows now carry a verdict, and every one of them is true —
    the fence was MISSING here, not merely unexercised, which is the same
    asymmetry the Register's volume bound had.

    NAMED REFUSAL, and it is the class the report actually counts. The verdict
    is a DIGIT COUNT and cannot reach "49 CFR 30166", because real parts do
    reach five digits (5 CFR 10001 exists). 21 distinct values / 126 rows are
    a U.S.C. section wearing a CFR label — "49 CFR 30166", "19 CFR 1202" (the
    Tariff Act), "42 CFR 1395r", "42 CFR 6912" — and the evidence that says so
    is not in the string:

    * the same RIN files the same numbers as ``usc`` with usc_title = cfr_title
      and usc_section = cfr_part, which needs the record, not the value;
    * the (title, part) pair is absent from the 29,503-entry CFR reference
      table this corpus builds, and from all 8,424 parts of the OFR's own 2025
      subject index — checked, and 0 of the 21 survive either.

    Both oracles are the builder's. A grammar that guessed from the shape
    alone would have to call 5 CFR 10001 damage too, so the reading stays as
    filed and the correction waits for a pass that can consult a record.
    """

    for text, part, verdict in (
        ("42 CFR 412106", "412106", False),
        ("47 CFR 634761471", "634761471", False),
        ("5 CFR 10001", "10001", True),
        ("49 CFR 30166", "30166", True),
        ("40 CFR 60", "60", True),
        ("49 CFR 1.95", "1", True),
    ):
        row = next(r for r in parse_authority_citation(text) if r.authority_type == "cfr")
        assert (row.cfr_part, row.cfr_part_is_plausible) == (part, verdict), text
        assert row.cfr_part_is_plausible == parse_cfr_citations(text)[0].part_is_plausible, text
    # NULL where there is no part to judge, never False.
    titleless = next(r for r in parse_authority_citation("3 CFR") if r.authority_type == "cfr")
    assert (titleless.cfr_part, titleless.cfr_part_is_plausible) == (None, None)
    # The refused population reads exactly as filed: a CFR part, unflagged by
    # this verdict, with the U.S.C. twin its own RIN also states left alone.
    for text, title, part in (
        ("49 CFR 30166", 49, "30166"),
        ("19 CFR 1202", 19, "1202"),
        ("42 CFR 1395r", 42, "1395r"),
    ):
        row = next(r for r in parse_authority_citation(text) if r.authority_type == "cfr")
        assert (row.cfr_title, row.cfr_part, row.cfr_part_is_plausible) == (title, part, True), text
        assert not any(r.authority_type == "usc" for r in parse_authority_citation(text)), text


#: (value, congress, volume the value states, source rows). Every one states a
#: real Statutes volume — 4 is 1824-1835, 11 is 1855-1859, 70 is 1956, 76 is
#: 1962 — which is exactly why nothing refused them.
STATUTES_VOLUME_CONTRADICTIONS = (
    ("PL 92-500 76 Stat. 816", 92, 76, 18),
    ("316, 332, 403, 615a–1, and 615c of Pub. L. 73–416, 4 Stat. 1064, as amended", 73, 4, 18),
    ("Reorganization Plan No. 7 of 1961, 26 FR 7315, August 12, 1961: PL 89-56, 70 Stat 195", 89, 70, 8),
    ("Pub. L. 98-192, Dec. 15, 1971, 85 Stat. 646", 98, 85, 8),
    ("Pub. L. 105-115, 11 Stat. 2322 (21 U.S.C. 355 note)", 105, 11, 6),
    ("Pub. L. 98-80, 84 Stat. 2086", 98, 84, 6),
    ("PL 104-191, 101 Stat 1936 (HIPAA)", 104, 101, 4),
    ("PL 99-625, 10 Stat 3500", 99, 10, 4),
)


def test_a_statutes_volume_is_fenced_by_the_public_law_beside_it() -> None:
    """ "PL 104-191, 101 Stat 1936" is HIPAA, and HIPAA is at 110 Stat. 1936.

    Four series carry a bound column and are loud; a Statutes volume that is
    REAL but belongs to a different Congress is inside every one of them.
    Volume 4 is 1824-1835, volume 11 is 1855-1859, volume 76 is 1962 — each a
    volume that exists, cited beside a law that cannot be in it, and flagged
    by nothing. 14 distinct values / 46 statute rows carry the contradiction,
    of which 9 rows are already loud on ``stat_volume_in_series`` (the three
    "188 Stat" variants), so the silent population this fence adds is 11
    values / 37 rows. Measured 2026-08-22.

    Neither half is checkable alone, so the verdict reads a NEIGHBOUR: the one
    Public Law standing textually adjacent to the Statutes cite. Adjacency is
    the whole precision story — punctuation and the law's own approval date
    may stand between them, a WORD may not — because "act A at Stat X **as
    amended by** act B" pairs two different laws and proves nothing. 793
    values state exactly one of each; 658 are adjacent in this sense.

    NAMED REFUSAL: the fence labels and does not correct. The relation gives
    each Congress TWO volumes, so a contradiction never leaves one survivor —
    "PL 104-191" admits both 109 and 110 Stat., and only a roster that knows
    HIPAA is at 110 Stat. 1936 can pick. That roster is the builder's; this
    module states the contradiction and stops. Nor can it say WHICH half is
    damaged: "Pub. L. 98-192, Dec. 15, 1971, 85 Stat. 646" is settled by its
    own date — December 1971 is the 92nd Congress, so the VOLUME is right and
    the Public Law number is wrong — and nothing in the shape says so.
    """

    for text, congress, volume, _rows in STATUTES_VOLUME_CONTRADICTIONS:
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert [(r.statute_volume, r.statute_volume_matches_public_law) for r in rows] == [(volume, False)], text
        assert any(r.public_law and r.public_law.startswith(f"{congress}-") for r in parse_authority_citation(text))
    # The canonical spellings the same corpus writes, and the same numbers
    # under a Congress that can carry them.
    for text in (
        "Pub. L. 104-191, 110 Stat. 1936",
        "PL 92-500, 86 Stat. 816",
        "Pub. L. 105-115, 111 Stat. 2296",
        "Pub. L. 73-416, 48 Stat. 1064",
        "Pub. L. 109-115, 119 Stat. 2936",
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert rows and all(row.statute_volume_matches_public_law for row in rows), text
    # NULL where there is nothing to judge: no Public Law beside the volume, a
    # word between the two, or a Congress outside the numbered series — which
    # ``pl_congress_in_series`` already reports, and about which the relation
    # says nothing.
    for text in (
        "117 Stat. 429",
        "Pub. L. 107-296, sec. 1512, as amended by the Homeland Security Act, 116 Stat. 2310",
        "PL 11-24, 123 Stat 1734",
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert rows and all(row.statute_volume_matches_public_law is None for row in rows), text


def test_a_lettered_page_is_fenced_by_the_same_public_law_beside_it() -> None:
    """A fence with a hole: the lettered-page reader minted a volume unjudged.

    ``statute_volume_matches_public_law`` was computed inside the INTEGER-page
    reader alone, and the appendix-paginated reader beside it mints the same
    ``statute_volume`` column from the same kind of string — so every lettered
    page carried a volume with a permanently NULL verdict. Not a silence about
    something unjudgeable: 30 distinct values / 369 rows of the pinned table
    state a lettered page with an integer volume, and 24 values / 328 rows of
    those state exactly one Public Law right there in the value.

    The verdict is now one expression both readers call, so the answer depends
    on the citation rather than on which reader happened to match it.

    NAMED REFUSAL, and it is the fence's own adjacency rule rather than a new
    gap: 4 values / 52 rows write the law's section BETWEEN the two halves —
    "PL 106-554, sec 1505, 114 Stat 2763A-326 to 2763A-328", 32 rows — and a
    WORD between a Public Law and a Statutes cite is what
    :data:`_PUBLIC_LAW_TO_STATUTE` refuses, because "act A at Stat X as amended
    by act B" pairs two different laws. They stay NULL, exactly as they would
    with an integer page. So the hoist answers 20 values / 276 rows, all of
    them True, and every one is Pub. L. 106-554 sec. 1505 at 114 Stat.
    2763A-326 (106th Congress, volumes 112-115).
    """

    for text in (
        "sec 1505 of PL 106-554, 114 Stat 2763A-326 to 2763A-328",
        "sec. 1505 of Pub. L. 106-554, 114 Stat. 2763A-326 to -328",
        "sec. 1505 of Pub. L. 106-554, 114 Stat. 2763A-326 to 328",
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert rows and all(row.statute_volume_matches_public_law for row in rows), text
    # The other side of the verdict. No corpus value states a lettered page
    # under a Congress that cannot carry its volume, so this is a deliberate
    # mutation of one that does: the 99th Congress ran 98-101 Stat., and 113
    # Stat. is the 106th's.
    for text in (
        "Pub. L. 99-113, 113 Stat. 1501A-293",
        "sec 1505 of PL 96-554, 114 Stat 2763A-326",
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert rows and all(row.statute_volume_matches_public_law is False for row in rows), text
    # The refusal, asserted so it stays a decision: a word between the halves.
    for text in (
        "PL 106-554, sec 1505, 114 Stat 2763A-326 to 2763A-328",
        "113 Stat 1501A-293",
    ):
        rows = [row for row in parse_authority_citation(text) if row.authority_type == "statute_at_large"]
        assert rows and all(row.statute_volume_matches_public_law is None for row in rows), text
    # A LETTERED VOLUME is not judged at all, and that is the fence's subject
    # rather than an omission: "70A Stat. 157" leaves statute_volume NULL
    # because 70A is not volume 70, and the relation judges integers.
    row = next(r for r in parse_authority_citation("Pub. L. 84-1028, 70A Stat. 157") if r.statute_volume_text)
    assert (row.statute_volume, row.statute_volume_matches_public_law) == (None, None)


#: What the corpus-derived ceiling catches in the pinned Agenda table, with
#: the section each value really names where the campaign settled it. Every
#: one carries a title that ``usc_title_is_possible`` calls real, which is the
#: point: the title was fenced and the section was not.
IMPOSSIBLE_MAGNITUDES = (
    (33, "70034", 9, "title 46, not 33 — the Ports and Waterways Safety Act moved"),
    (33, "70116", 9, "46 U.S.C. 70116, port and facility security"),
    (42, "512651c", 8, "damaged beyond recovery"),
    (29, "60129", 4, "title 29 stops near 3211"),
    (49, "601132", 3, "a doubled token"),
    (21, "890890", 3, "a doubled token"),
    (47, "44715", 2, "49 U.S.C. 44715 — aviation, not telecom"),
    (47, "44712", 2, "49 U.S.C. 44712 — aviation, not telecom"),
    (26, "98332", 2, "unrecovered"),
    (8, "81611", 2, "the title glued to its own section span, 1611-1613"),
)


def test_the_structure_census_is_the_grammars_own_and_cannot_drift() -> None:
    """Every word the census calls citation structure, matched by the pattern
    that names it.

    The census exists for a caller outside this module -- a repair fence has to
    tell "et seq." beside a damaged label from prose beside one -- and a census
    kept by hand would drift from the patterns silently. So each entry carries
    the pattern that names it and a phrase that proves the pairing, and this
    walks the table: a word the grammar stops reading breaks a pin here rather
    than widening a fence somewhere else.
    """

    from spicy_docs.interpretation.citation_grammar import (
        _STRUCTURE_WORD_WITNESSES,
        CITATION_STRUCTURE_WORDS,
        names_citation_structure,
    )

    assert set(_STRUCTURE_WORD_WITNESSES) == set(CITATION_STRUCTURE_WORDS)
    for word, (pattern, phrase) in _STRUCTURE_WORD_WITNESSES.items():
        assert re.search(pattern, phrase, re.IGNORECASE), (word, pattern, phrase)
        assert word in phrase.lower(), (word, phrase)

    # Case and punctuation are presentation: the corpus writes "Sec.", "SEC"
    # and "sec" for one marker, and "note" arrives with the comma still on it.
    assert names_citation_structure("Sec.") is True
    assert names_citation_structure("ET") is True
    assert names_citation_structure(" note ") is True
    # And what it must NOT call structure: the halves of a scheme label the
    # filer split, and ordinary prose.
    assert [names_citation_structure(word) for word in ("Pu.", "Pub.", "USC", "Articles", "Plan", "")] == [False] * 6


def test_a_range_keeps_its_far_end_in_the_four_places_it_was_losing_it() -> None:
    """Five shapes stated a range and published only where it began.

    Each one is the same sentence in a different position, and each was
    measured on rebuild #11 before it was fixed:

    IN A LIST (191 values / 3,880 rows, the largest). "20 U.S.C. 1406, 1431
    through 1444" published 1406 and 1431 and dropped 1444, while the identical
    range standing ALONE kept it -- the list tail had no range tail at all. The
    pair is the proof: the same words, two positions, two answers.

    A COMPOUND ENDPOINT (43 / 491). "16 U.S.C. 460k to 460k-4" is the Refuge
    Recreation Act entire, and the endpoint slot took a bare token, so it
    captured "460k", left "-4" behind, and the pair no longer ascended.
    Ordering it needs the third component of :func:`_usc_section_key`: the
    Code numbers a run of inserted sections 460k, 460k-1 ... 460k-4.

    A PARENTHESISED ENDPOINT (57 / 249). "42 U.S.C. 405(d) to 506 (h)" names a
    subsection at each end, and the parenthesis broke the adjacency the tail
    needs. The row stays "partial", because the trailing subsection is still
    uncovered text -- "42 USC 9608 (b)" is the module's own worked example of
    that and is unchanged.

    A SPELLED SHORTHAND (54 / 149). "12 USC 1817 to 19" is the abbreviation
    "1817-19" with the publisher's word in place of the publisher's hyphen, and
    the module read one and refused the other. They now give the identical
    answer, guards and all.

    AND THE TRAP (19 / 63), which is not a range at all: "12 U.S.C. 1422 to 12
    U.S.C. 1424" is two citations, and the failed endpoint capture BACKTRACKED
    into the second one's title -- matching the single digit "1", where the
    "another citation ahead" guard is satisfied because "2 U.S.C." is not a
    code name -- so the scan resumed inside "12" and the whole second citation
    vanished. An atomic endpoint refuses to give back what it matched.
    """

    # IN A LIST, and the paired proof that the two positions now agree.
    listed = parse_authority_citation("20 U.S.C. 1406, 1431 through 1444")
    assert [(c.usc_section, c.usc_section_end) for c in listed] == [("1406", None), ("1431", "1444")]
    alone = parse_authority_citation("20 U.S.C. 1431 through 1444")[0]
    assert (alone.usc_section, alone.usc_section_end) == ("1431", "1444")
    assert [
        (c.usc_section, c.usc_section_end) for c in parse_authority_citation("16 USC 460k to 460k-4, 668dd to 668ee")
    ] == [("460k", "460k-4"), ("668dd", "668ee")]

    # A COMPOUND ENDPOINT, and the ordering that reaches it.
    compound = parse_authority_citation("16 U.S.C. 460k to 460k-4")[0]
    assert (compound.usc_section, compound.usc_section_end) == ("460k", "460k-4")
    assert compound.usc_section_span_rule == citation_grammar.USC_SPAN_STATED
    assert citation_grammar._usc_section_key("460k") < citation_grammar._usc_section_key("460k-4")
    # And the truncation it replaces: the endpoint used to lose its own leaf.
    truncated = parse_authority_citation("12 USC 1702 to 1715z-21")[0]
    assert (truncated.usc_section, truncated.usc_section_end) == ("1702", "1715z-21")

    # A PARENTHESISED ENDPOINT -- read, and still partial for the tail it drops.
    paren = parse_authority_citation("42 U.S.C. 405(d) to 506 (h)")[0]
    assert (paren.usc_section, paren.usc_section_end) == ("405", "506")
    assert paren.parse_status == "partial"
    # The pinpoint is tolerated only INSIDE the range tail: a subsection with no
    # range behind it is uncovered text and its row says so.
    assert parse_authority_citation("42 USC 9608 (b)")[0].parse_status == "partial"

    # A SPELLED SHORTHAND, and its hyphenated twin, character for character.
    for text in ("12 USC 1817 to 19", "12 USC 1817-19"):
        row = parse_authority_citation(text)[0]
        assert (row.usc_section, row.usc_section_end) == ("1817", "1819"), text
        assert row.usc_section_span_rule == citation_grammar.USC_SPAN_ABBREVIATED, text
        assert row.parse_status == "partial", text
    # The abbreviation's own guards still refuse, whichever separator is used.
    assert parse_authority_citation("5 USC 706 to 6")[0].usc_section_end is None
    assert parse_authority_citation("50 U.S.C. 4801 to 4582")[0].usc_section_end is None

    # THE TRAP: two citations, two rows, no range.
    trap = parse_authority_citation("12 U.S.C. 1422 to 12 U.S.C. 1424")
    assert [(c.usc_title, c.usc_section, c.usc_section_end) for c in trap] == [
        (12, "1422", None),
        (12, "1424", None),
    ]
    # The spaced-dash spelling of the same trap, which the guard's own docstring
    # named and which lost its second citation the same way.
    dashed = parse_authority_citation("7 U.S.C. 6501 - 7 U.S.C. 6524")
    assert [(c.usc_title, c.usc_section, c.usc_section_end) for c in dashed] == [
        (7, "6501", None),
        (7, "6524", None),
    ]
    # And an ordinary range is untouched by all of it.
    for text, first, last in (
        ("5 USC 551 to 557", "551", "557"),
        ("12 USC 1422 to 1424", "1422", "1424"),
        ("42 U.S.C. 7401-7671q", "7401", "7671q"),
    ):
        row = parse_authority_citation(text)[0]
        assert (row.usc_section, row.usc_section_end) == (first, last), text
        assert row.parse_status == "ok", text


# --------------------------------------------------------------------------- #
# New in spicy-docs: Public Law and Statutes at Large occurrences in running
# text, read through the tables the field reader reads them by.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(Pub. L. 104-13, 44 U.S.C. 3506)", [("104-13", "Pub. L. 104-13")]),
        # A space after the dash, and an en dash the span keeps as printed.
        ("Public Law 92- 463, notice is given", [("92-463", "Public Law 92- 463")]),
        ("P.L. 118–63", [("118-63", "P.L. 118–63")]),
        # The dot-for-dash damage the field reader already repairs.
        ("Pub. L 103.311", [("103-311", "Pub. L 103.311")]),
        # Every occurrence, not every distinct law.
        ("P.L. 94-409 and P.L. 94-409", [("94-409", "P.L. 94-409"), ("94-409", "P.L. 94-409")]),
        # Refused as the field reader refuses them.
        ("Pub. L. 112-055", []),
        ("Public Lands and Republic Law 5", []),
    ],
)
def test_a_public_law_occurrence_is_located_in_running_text(text: str, expected: list) -> None:
    """The span re-reads as the printed characters; the law is read as integers."""
    found = citation_grammar.find_public_law_citations(text)
    assert [(o.citation.public_law, o.text) for o in found] == expected
    assert all(text[o.start : o.end] == o.text for o in found)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pub. L. 107-347, 116 Stat 2962", [(116, None, 2962, None, True, "116 Stat 2962")]),
        ("(Pub. L. 92-463; 86 Stat.770)", [(86, None, 770, None, True, "86 Stat.770")]),
        ("113 Stat. 1501A-293", [(113, None, None, "1501A-293", None, "113 Stat. 1501A-293")]),
        (
            "114 Stat. 2763A-326 to 2763A-328 (2000)",
            [(114, None, None, "2763A-326 to 2763A-328", None, "114 Stat. 2763A-326 to 2763A-328")],
        ),
        ("70A Stat. 157", [(None, "70A", 157, None, None, "70A Stat. 157")]),
        ("Stat. of the Union and 12 State 45", []),
    ],
)
def test_a_statutes_occurrence_is_located_in_running_text(text: str, expected: list) -> None:
    """Volume and page as the field reader states them, with its neighbour verdict and a span covering the row."""
    found = citation_grammar.find_statute_citations(text)
    assert [
        (
            o.citation.statute_volume,
            o.citation.statute_volume_text,
            o.citation.statute_page,
            o.citation.statute_page_text,
            o.citation.statute_volume_matches_public_law,
            o.text,
        )
        for o in found
    ] == expected
    assert all(text[o.start : o.end] == o.text for o in found)


@pytest.mark.parametrize(
    "text",
    [
        "Pub. L. 107-347, 116 Stat 2962, 44 U.S.C. 3501 note",
        "Public Law 92- 463 and P.L. 94-409; 86 Stat. 770",
        "113 Stat. 1501A-293, 70A Stat. 157 and Pub. L 103.311",
        "PL 98-500 76 Stat. 816",
    ],
)
def test_the_occurrence_readers_state_what_the_field_reader_states(text: str) -> None:
    """One table, two readers: the rows the field reader states are the rows the occurrences carry."""
    fields = parse_authority_citation(text)
    for family, finder in (
        ("public_law", citation_grammar.find_public_law_citations),
        ("statute_at_large", citation_grammar.find_statute_citations),
    ):
        stated = {replace(row, parse_status="ok") for row in fields if row.authority_type == family}
        located = {replace(o.citation, parse_status="ok") for o in finder(text)}
        assert located == stated, (family, text)
