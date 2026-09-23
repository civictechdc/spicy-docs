"""Annual CFR sections take their part from the enclosing PART heading, never the number or granule id.

Excerpts are cut from retained 2025 annual volumes (see fixtures/cfr/README.md):
subpart-numbered Title 43, compound Title 41 parts and its wrapper section,
unclosed revised text that swallows later parts, headings the pattern must stop
inside, wrong running heads, revised and repeated copies, publisher typos and
duplicates, whitespace-only numbers and Title 14 Part 241's own numbering.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from spicy_docs.interpretation.citations import find_citations
from spicy_docs.sources.cfr import (
    AnnualCfrSelection,
    CfrSourceError,
    annual_cfr_granule_token,
    annual_cfr_xml_locator,
    scan_annual_cfr_sections,
    split_annual_cfr_section,
)
from spicy_docs.sources.cfr_section_number import CFR_SECTION_NUMBER

FIXTURES = Path(__file__).parent / "fixtures" / "cfr"


def scan(package, body=None):
    """Scan one retained excerpt, or a mutation of its bytes."""
    body = (FIXTURES / "ancestry" / f"{package}.xml").read_bytes() if body is None else body
    return scan_annual_cfr_sections(body)


def by_number(sections):
    """The canonical copy of each printed number."""
    return {section.number: section for section in sections if section.canonical}


def split(section):
    """Split a scanned section under its own heading part and subpart."""
    return split_annual_cfr_section(section.number, section.part, section.subpart)


def test_title_43_part_is_the_heading_and_its_citation_is_the_printed_number():
    """§ 1601.0-1 sits in PART 1600, Subpart 1601: part 1600, and the Federal Register's own key (ruling 5)."""
    sections = by_number(scan("CFR-2025-title43-vol2"))
    first = sections["§\u20091601.0-1"]
    assert (first.part, first.subpart, first.running_head, first.granule) == ("1600", "1601", "Pt. 1600", "1601-0-1")
    number = split(first)
    assert (number.printed_part, number.section, number.citation) == ("1601", "1601.0-1", "1601.0-1")
    assert number.citation_joins and not number.mismatch and not number.range
    (finding,) = find_citations("43 CFR 1601.0-1", kinds=("cfr_section",))
    assert finding.target_key == f"43-{number.citation}"
    assert split(sections["§\u20091610.1"]).citation == "1610.1"
    # The same number without its subpart is a printed part the heading does not name.
    assert split_annual_cfr_section(first.number, "1600", None).mismatch


def test_compound_parts_keep_their_hyphen_and_placeholders_hold_no_sections():
    """Title 41's PART 50-201 is not cut at the hyphen; a PARTS placeholder contributes no section."""
    sections = scan("CFR-2025-title41-vol1")
    assert [section.part for section in sections] == ["50-201", "50-201", "51-10"]
    number = split(sections[0])
    assert (sections[0].granule, number.section, number.citation) == ("50-201-1", "1", "50-201.1")
    ranged = sections[-1]
    assert ranged.reserved and ranged.granule == "51-10-104-51-10-109"
    assert split(ranged).range and split(ranged).citation is None


def test_wrapper_section_nests_whole_parts_under_their_own_headings():
    """Title 41 vol 4 prints § 201-1.304 around the FTR: nested sections take the innermost PART."""
    sections = scan("CFR-2025-title41-vol4")
    assert [(s.number, s.part, s.nested, s.wrapped) for s in sections] == [
        ("§\u2009201-1.303", "201-1", False, False),
        ("§\u2009201-1.304", "201-1", False, False),
        ("§\u2009300-1.1", "300-1", True, True),
        ("§\u2009300-2.1", "300-2", True, True),
    ]
    assert all(section.canonical and not section.revised for section in sections)


def test_unclosed_revised_text_swallows_the_parts_that_follow():
    """15 CFR vol 1 prints PART 8 onward inside § 6.5's revised text: nested and revised, yet the only, current copy."""
    sections = scan("CFR-2025-title15-vol1")
    assert [(s.number, s.part, s.nested, s.wrapped, s.revised, s.canonical) for s in sections] == [
        ("§\u20096.1", "6", False, False, False, True),
        ("§\u20096.5", "6", False, False, False, True),
        ("§\u20096.1", "6", True, False, True, False),
        ("§\u20096.5", "6", True, False, True, False),
        ("§\u20098.1", "8", True, True, True, True),
    ]
    assert split(sections[-1]).citation == "8.1"


def test_outer_numbered_subpart_does_not_reach_a_nested_part():
    """A part-width subpart of the wrapper's PART does not number sections of a PART printed inside the wrapper."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title41-vol4.xml").read_bytes()
    heading, number = b"Subpart C\xe2\x80\x94Exclusion", "§\u2009300-1.1".encode()
    assert body.count(heading) == 1 and body.count(number) == 1
    body = body.replace(heading, "Subpart 300-9—Exclusion".encode()).replace(number, "§\u2009300-9.1".encode())
    wrapper, nested = scan("CFR-2025-title41-vol4", body)[1:3]
    assert (wrapper.part, wrapper.subpart) == ("201-1", "300-9")
    assert (nested.part, nested.subpart) == ("300-1", None)
    assert split(nested).mismatch and split(nested).citation is None


@pytest.mark.parametrize(
    "package,part",
    [
        ("CFR-2025-title7-vol1", "8"),  # PART 8—4-H CLUB NAME AND EMBLEM
        ("CFR-2025-title13-vol1", "124"),  # PART 124—8(a) BUSINESS DEVELOPMENT…
        ("CFR-2025-title39-vol1", "1"),  # PART 1-POSTAL POLICY (ARTICLE I)
        ("CFR-2025-title12-vol5", "326"),  # a heading that begins with a newline
    ],
)
def test_heading_number_stops_at_the_dash_that_ends_it(package, part):
    """The heading number ends at the title's dash, before any dash inside the title's words."""
    assert {section.part for section in scan(package)} == {part}


def test_running_head_never_substitutes_for_the_heading():
    """12 CFR vol 10 prints ``Pt. 1208`` over ``PART 1209``; without a heading the part is unknown, not 1208."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title12-vol10.xml").read_bytes()
    first = scan("CFR-2025-title12-vol10", body)[0]
    assert (first.part, first.running_head) == ("1209", "Pt. 1208")
    heading = '<HD SOURCE="HED">PART 1209—RULES OF PRACTICE AND PROCEDURE</HD>'.encode()
    assert heading in body
    headless = scan("CFR-2025-title12-vol10", body.replace(heading, b""))[0]
    assert (headless.part, headless.running_head) == (None, "Pt. 1208")


def test_revised_copy_is_kept_flagged_and_not_canonical():
    """§ 1282.1 carries its own revised text; both copies stay, and the un-nested one answers the granule."""
    current, revised = scan("CFR-2025-title12-vol10")[1:]
    assert current.granule == revised.granule == "1282-1" and current.part == revised.part == "1282"
    assert (current.nested, current.revised, current.canonical) == (False, False, True)
    assert (revised.nested, revised.wrapped, revised.revised, revised.canonical) == (True, False, True, False)
    assert not current.repeated and not revised.repeated


def test_un_nested_copy_is_canonical_even_when_a_nested_copy_comes_first():
    """Document order does not decide: a later un-nested copy replaces an earlier nested one."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title41-vol4.xml").read_bytes()
    closing = b"</SECTION>\n     </SUBPART>"
    assert body.count(closing) == 1
    sections = scan(
        "CFR-2025-title41-vol4",
        body.replace(closing, "</SECTION><SECTION><SECTNO>§\u2009300-1.1</SECTNO></SECTION></SUBPART>".encode()),
    )
    nested, outer = [section for section in sections if section.granule == "300-1-1"]
    assert nested.nested and not nested.canonical
    assert not outer.nested and outer.canonical and outer.part == "201-1"


def test_un_revised_copy_is_canonical_even_when_a_revised_copy_comes_first():
    """Among un-nested copies the un-revised one answers, whatever the order."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title12-vol9.xml").read_bytes()
    number, closing = "§\u20091033.101".encode(), b"</APPENDIX>\n    </SUBPART>"
    assert body.count(number) == 2 and body.count(closing) == 1
    body = body.replace(number, "§\u20091033.102".encode(), 1)
    body = body.replace(closing, closing + b"<SUBPART><SECTION><SECTNO>" + number + b"</SECTNO></SECTION></SUBPART>")
    revised, current = [section for section in scan("CFR-2025-title12-vol9", body) if section.granule == "1033-101"]
    assert revised.revised and not revised.canonical
    assert not current.revised and current.canonical and revised.repeated and current.repeated


def test_un_revised_publisher_duplicate_is_kept_and_flagged():
    """48 CFR vol 5 prints § 849.504 twice under the same subpart heading; the first answers."""
    first, second = scan("CFR-2025-title48-vol5")
    assert first.granule == second.granule == "849-504" and first.part == second.part == "849"
    assert not (first.nested or first.revised or second.nested or second.revised)
    assert first.repeated and second.repeated and first.canonical and not second.canonical


def test_whitespace_only_numbers_are_never_canonical():
    """17 CFR vol 5 prints two SECTNOs holding an em space: kept as printed, with an empty token that answers nothing."""
    sections = scan("CFR-2025-title17-vol5")
    assert [section.number for section in sections] == ["\u2003", "\u2003"]
    assert all(s.granule == "" and not s.canonical and not s.repeated and s.part is None for s in sections)
    assert split(sections[0]).citation is None


def test_numbered_subpart_outside_title_43_does_not_cite():
    """NASA numbers subparts 1, 2, …: § 1201.100 cites under its part, and a printed ``1.`` prefix is no citation."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title14-vol5.xml").read_bytes()
    (section,) = scan("CFR-2025-title14-vol5", body)
    assert (section.part, section.subpart, split(section).citation) == ("1201", "1", "1201.100")
    number = "§\u20091201.100".encode()
    assert body.count(number) == 1
    (renumbered,) = scan("CFR-2025-title14-vol5", body.replace(number, "§\u20091.100".encode()))
    assert split(renumbered).mismatch and split(renumbered).citation is None


def test_repeated_un_nested_copies_are_both_kept_and_flagged():
    """A PART-level effective-date note reprints § 1033.101 outside any SECTION; both copies share part 1033."""
    first, second = scan("CFR-2025-title12-vol9")
    assert first.granule == second.granule and first.part == second.part == "1033"
    assert first.repeated and second.repeated and not first.nested and not second.nested
    assert (first.canonical, first.revised) == (True, False) and (second.canonical, second.revised) == (False, True)


def test_title_14_part_241_numbering_is_flagged_not_cited():
    """Part 241 prints ``Section 01``, ``Sec. 1-1`` and ``19-8.1``; each keeps part 241 and has no citation."""
    sections = by_number(scan("CFR-2025-title14-vol4"))
    assert {section.part for section in sections.values()} == {"241"}
    reserved = sections["Section 01"]
    assert reserved.reserved and reserved.granule == "Section01"
    assert not sections["Section 03"].reserved
    unprefixed = split(sections["Sec. 1-1"])
    assert sections["Sec. 1-1"].granule == "Sec-1-1"
    assert (unprefixed.printed_part, unprefixed.citation, unprefixed.mismatch) == (None, None, False)
    for number in ("19-8.1", "§\u200919-8.3"):
        parts = split(sections[number])
        assert parts.printed_part == "19-8" and parts.mismatch and parts.citation is None
        assert parts.section == parts.number


def test_publisher_typo_keeps_the_heading_part_and_loses_its_citation():
    """30 CFR prints § 206.253 inside PART 1206."""
    neighbour, typo = scan("CFR-2025-title30-vol3")
    assert split(neighbour).citation == "1206.252"
    parts = split(typo)
    assert typo.part == "1206" and parts.mismatch and parts.citation is None and parts.section == "206.253"


def test_parenthesized_numbers_cite_and_single_section_mark_ranges_do_not():
    """Parentheses stay in the citation and drop from the granule; ``§ 1.404(a)-4-1.404(a)-7`` is a span."""
    single, span = scan("CFR-2025-title26-vol6")
    assert single.granule == "1-401k-1"
    assert (split(single).section, split(single).citation) == ("401(k)-1", "1.401(k)-1")
    assert split(span).range and split(span).citation is None and not split(span).citation_joins


def test_parenthesized_citation_does_not_join_the_federal_register_key():
    """Today's Federal Register ``cfr_section`` key stops at the parenthesis; B4 decides one spelling for both sides."""
    (single,) = [s for s in scan("CFR-2025-title26-vol6") if s.granule == "1-401k-1"]
    assert split(single).citation == "1.401(k)-1" and not split(single).citation_joins
    (finding,) = find_citations("26 CFR 1.401(k)-1", kinds=("cfr_section",))
    assert finding.target_key == "26-1.401"


def test_section_outside_any_part_has_no_part():
    """48 CFR vol 2 reprints § 1.106 in its OMB back matter, outside every PART."""
    (reprint,) = scan("CFR-2025-title48-vol2")
    assert (reprint.part, reprint.running_head, reprint.subpart) == (None, None, None)
    assert split(reprint).citation is None


@pytest.mark.parametrize(
    "printed,part,subpart,expected",
    [
        # (number, printed_part, section, citation, range, mismatch)
        ("§§\u200988.2 through 88.3", "88", None, ("88.2through88.3", "88", "2through88.3", None, True, False)),
        ("§§\u2009457.104-457.109", "457", None, ("457.104-457.109", "457", "104-457.109", None, True, False)),
        ("1509.203-1519.204", "1519", None, ("1509.203-1519.204", "1509", "1509.203-1519.204", None, True, True)),
        (
            "§\u2009109-38.301-1.50",
            "109-38",
            None,
            ("109-38.301-1.50", "109-38", "301-1.50", "109-38.301-1.50", False, False),
        ),
        ("§\u2009752.1.", "752", None, ("752.1", "752", "1", "752.1", False, False)),
        ("§\u2009261a.1", "261a", None, ("261a.1", "261a", "1", "261a.1", False, False)),
        ("§\u2009105.60.001", "105-60", None, ("105.60.001", "105", "105.60.001", None, False, True)),
        ("\u2003", None, None, ("", None, "", None, False, False)),
    ],
)
def test_split_reads_every_printed_form(printed, part, subpart, expected):
    """Printed forms from the 2025 volumes split into citation parts with range and mismatch flags."""
    parts = split_annual_cfr_section(printed, part, subpart)
    assert (parts.number, parts.printed_part, parts.section, parts.citation, parts.range, parts.mismatch) == expected


@pytest.mark.parametrize(
    "printed,token",
    [
        ("§\u20091.401(k)-1", "1-401k-1"),
        ("Sec. 1-1", "Sec-1-1"),
        ("§§\u20090.735-10a—0.735-15", "0-735-10a-0-735-15"),
        ("§\u2009752.1.", "752-1-"),
    ],
)
def test_granule_token_matches_govinfo_spelling(printed, token):
    """Tokens equal GovInfo's own granule suffixes, including its trailing-period ``sec752-1-``."""
    assert annual_cfr_granule_token(printed) == token


def test_granule_token_is_the_old_locator_spelling_for_every_accepted_number():
    """For every number the selector grammar accepts, the token is the locator's former ``.``-to-``-`` spelling."""
    rng = random.Random(20260923)
    grammar = re.compile(CFR_SECTION_NUMBER)

    def run(letters=""):
        return "".join(rng.choices("0123456789", k=rng.randint(1, 5))) + letters

    for _ in range(2000):
        part = "-".join(run() for _ in range(rng.randint(1, 3)))
        section = "-".join(run(rng.choice(["", rng.choice("abcxyzABCXYZ")])) for _ in range(rng.randint(1, 3)))
        number = f"{part}.{section}"
        assert grammar.fullmatch(number)
        assert annual_cfr_granule_token(number) == number.replace(".", "-")
        assert annual_cfr_xml_locator(AnnualCfrSelection(2025, 1, 1, number)).endswith(
            f"-sec{number.replace('.', '-')}.xml"
        )


def test_locator_uses_the_shared_token_and_accepts_volume_zero():
    """The section locator spells its granule with the shared token; GovInfo publishes vol0 packages."""
    assert annual_cfr_xml_locator(AnnualCfrSelection(2025, 43, 2, "1601.0-1")).endswith(
        "/CFR-2025-title43-vol2/xml/CFR-2025-title43-vol2-sec1601-0-1.xml"
    )
    assert annual_cfr_xml_locator(AnnualCfrSelection(2026, 14, 0)).endswith("/title-14/CFR-2026-title14-vol0.xml")
    with pytest.raises(CfrSourceError, match="volume"):
        AnnualCfrSelection(2026, 14, -1)


@pytest.mark.parametrize(
    "body,match",
    [
        ((FIXTURES / "annual-title30-vol3-sec716-2.xml").read_bytes(), "root"),
        (b"<CFRDOC><PART><CFRDOC/></PART></CFRDOC>", "nested document root"),
        (b'<!DOCTYPE CFRDOC [<!ENTITY x "y">]><CFRDOC/>', "DOCTYPE"),
    ],
)
def test_scan_refuses_anything_but_one_volume(body, match):
    """A granule, a nested document root and an internal DTD are refused."""
    with pytest.raises(CfrSourceError, match=match):
        scan_annual_cfr_sections(body)


def test_scan_respects_the_byte_bound():
    """The byte bound is checked before parsing."""
    body = (FIXTURES / "ancestry" / "CFR-2025-title43-vol2.xml").read_bytes()
    with pytest.raises(CfrSourceError, match="max_bytes"):
        scan_annual_cfr_sections(body, max_bytes=len(body) - 1)
