"""Publisher-shaped regression cases moved from SpicySearch with their source IDs."""

from spicy_docs.sources.federal_register import list_of_subjects
from spicy_docs.sources.federal_register.list_of_subjects import (
    extract_blocks_from_text_body,
    extract_blocks_from_xml_body,
    is_cfr_subheading,
    printed_cfr_subheadings,
    split_printed_atoms,
    strip_markup,
    unread_subheading_candidate,
)


def test_xml_subjects_preserve_paragraph_order_and_repeated_blocks() -> None:
    body = """<RULE>
      <P>Unrelated preamble.</P>
      <LSTSUB>
        <HD>List of Subjects in 12 CFR Parts 1 and 2</HD>
        <HD>12 CFR Part 1</HD>
        <P> Banks &amp; banking, <E T="03">Consumer protection</E>. </P>
        <P>   </P>
        <HD>12 CFR Part 2</HD>
        <P> Banks &amp; banking, <E T="03">Consumer protection</E>. </P>
      </LSTSUB>
      <LSTSUB><HD>15 CFR Part 1</HD><P>Exports,\n Safety.</P></LSTSUB>
      <P>Unrelated closing instructions.</P>
    </RULE>"""
    assert extract_blocks_from_xml_body(body) == (
        "Banks & banking, Consumer protection.",
        "Banks & banking, Consumer protection.",
        "Exports, Safety.",
    )


def test_the_text_carrier_reads_the_single_part_shape() -> None:
    """``99-33554`` -- the heading names the part, the terms follow it."""

    body = (
        "<html><body><pre>Some preamble prose.\n\n"
        "List of Subjects in 34 CFR Part 614\n\n"
        "    Exports, Reporting and recordkeeping requirements.\n\n"
        "(Program Authority: 20 U.S.C. 6832)\n\n"
        "    Dated: December 21, 1999.\n</pre></body></html>"
    )
    blocks = extract_blocks_from_text_body(body)
    assert blocks == ("Exports, Reporting and recordkeeping requirements.",)


def test_the_text_carrier_reads_the_multi_part_shape() -> None:
    """``94-14486`` -- a bare heading, then one sub-heading per amended part."""

    body = (
        "List of Subjects\n\n"
        "15 CFR Parts 771, 773 and 786\n\n"
        "    Exports, Reporting and recordkeeping requirements.\n\n"
        "15 CFR Part 779\n\n"
        "    Computer technology, Exports, Science and technology.\n\n"
        "    1. The authority citation continues to read as follows:\n"
    )
    blocks = extract_blocks_from_text_body(body)
    assert blocks == (
        "Exports, Reporting and recordkeeping requirements.",
        "Computer technology, Exports, Science and technology.",
    )


def test_96_12485_reads_terms_glued_under_the_heading() -> None:
    """``96-12485`` -- EPA prints the terms in the heading's own paragraph,
    no blank line between. Testing the whole paragraph for ``CFR`` instead
    of just its first line passed here too, and then swallowed the *next*
    paragraph -- the ``Dated:`` signature block -- as if it were the terms,
    discarding the eleven the heading paragraph actually carried.
    """

    body = (
        "costs associated with response efforts.\n"
        "List of Subjects in 40 CFR Part 300\n"
        "    Environmental protection, Air pollution control, Chemicals, \n"
        "Hazardous waste, Hazardous substances, Intergovernmental relations, \n"
        "Penalties, Reporting and recorkeeping requirements, Superfund, Water \n"
        "pollution control, Water supply.\n\n"
        "    Dated: May 6, 1996.\n"
        "A. Stanley Meiburg,\n"
        "Acting Regional Administrator, USEPA Region 4.\n\n"
    )
    blocks = extract_blocks_from_text_body(body)
    assert blocks == (
        (
            "Environmental protection, Air pollution control, Chemicals, "
            "Hazardous waste, Hazardous substances, Intergovernmental relations, "
            "Penalties, Reporting and recorkeeping requirements, Superfund, Water "
            "pollution control, Water supply."
        ),
    )
    assert split_printed_atoms(blocks[0]) == (
        "Environmental protection",
        "Air pollution control",
        "Chemicals",
        "Hazardous waste",
        "Hazardous substances",
        "Intergovernmental relations",
        "Penalties",
        "Reporting and recorkeeping requirements",
        "Superfund",
        "Water pollution control",
        "Water supply",
    )


def test_98_4853_a_wrapped_plural_heading_is_not_read_as_glued_terms() -> None:
    """``98-4853`` -- ``Lists of Subjects in 48 CFR Parts ...`` names 18
    parts and wraps onto a second line before the real, blank-line-separated
    terms paragraph.

    No shape-A case with a plural ``Lists of Subjects`` heading turned up in
    the 31,130-body pre-2000 corpus this fix was checked against, but this
    wrapped heading is exactly what a fix that only tested the first line
    for ``CFR`` -- without also checking whether what follows reads like a
    term -- would mistake for one: its continuation line, ``1815, 1816, ...
    and``, contains no word outside the CFR-heading vocabulary, so treating
    it as a printed term would inject bare part numbers as a "term" and,
    worse, orphan the real terms paragraph that follows.
    """

    body = (
        "published previously for public comment.\n\n"
        "Lists of Subjects in 48 CFR Parts 1801, 1802, 1803, 1804, 1805, 1814, \n"
        "1815, 1816, 1817, 1832, 1834, 1835, 1842, 1844, 1852, 1853, 1871, and \n"
        "1872\n\n"
        "    Government procurement.\n"
        "Deidre A. Lee,\n"
        "Associate Administrator for Procurement.\n\n"
    )
    blocks = extract_blocks_from_text_body(body)
    assert split_printed_atoms(blocks[0]) == ("Government procurement",)


def test_97_23498_reads_terms_glued_under_a_cfr_subheading() -> None:
    """``97-23498`` -- two of twelve CFR sub-headings (``16 CFR Part 1021``,
    ``16 CFR Part 1051``) are printed glued directly to their own terms, no
    blank line between. Testing the whole paragraph with
    ``is_cfr_subheading`` failed on the fused text and ended the
    alternation right there, losing every part from 1021 on -- including
    1051, 1115, and the rest actually printed after it.
    """

    body = (
        "List of Subjects\n\n"
        "16 CFR Part 1000\n\n"
        "    Organization and functions (Government agencies).\n\n"
        "16 CFR Part 1014\n\n"
        "    Privacy\n\n"
        "16 CFR Part 1021 \n"
        "    Environmental impact statements.\n\n"
        "16 CFR Part 1051 \n"
        "    Administrative practice and procedure, consumer protection.\n\n"
        "16 CFR Part 1115\n\n"
        "    Administrative practice and procedure, business and industry, \n"
        "consumer protection, reporting and recordkeeping requirements.\n\n"
        "    Accordingly, 16 CFR chapter II is amended as follows:\n"
    )
    blocks = extract_blocks_from_text_body(body)
    assert blocks == (
        "Organization and functions (Government agencies).",
        "Privacy",
        "Environmental impact statements.",
        "Administrative practice and procedure, consumer protection.",
        (
            "Administrative practice and procedure, business and industry, "
            "consumer protection, reporting and recordkeeping requirements."
        ),
    )


def test_95_21571_reads_terms_fused_to_the_next_subheading() -> None:
    """``95-21571`` -- the terms for part 353 run directly into the heading
    for part 870, no blank line between.

    The existing ``_page_marker_replacement`` fix handles this fusion only
    when a page marker sits at the seam; here the publisher simply omitted
    the blank line, and treating the fused paragraph as the terms for 353
    alone lost parts 870 and 890 outright: ``Hostages``, ``Iraq``,
    ``Kuwait``, ``Lebanon``, ``Life insurance``, ``Retirement``, ``Health
    facilities``, ``Health insurance``.
    """

    body = (
        "List of Subjects\n\n"
        "5 CFR Part 353\n\n"
        "    Administrative practice and procedure, Government employees.\n"
        "5 CFR Part 870\n\n"
        "    Administrative practice and procedure, Government employees, \n"
        "Hostages, Iraq, Kuwait, Lebanon, Life insurance, Retirement.\n\n"
        "5 CFR Part 890\n\n"
        "    Administrative practice and procedure, Government employees, Health \n"
        "facilities, Health insurance, Health professions, Hostages, Iraq, \n"
        "Kuwait, Lebanon, Reporting and recordkeeping requirements, Retirement.\n\n"
        "Office of Personnel Management,\n"
    )
    blocks = extract_blocks_from_text_body(body)
    assert blocks == (
        "Administrative practice and procedure, Government employees.",
        (
            "Administrative practice and procedure, Government employees, "
            "Hostages, Iraq, Kuwait, Lebanon, Life insurance, Retirement."
        ),
        (
            "Administrative practice and procedure, Government employees, Health "
            "facilities, Health insurance, Health professions, Hostages, Iraq, "
            "Kuwait, Lebanon, Reporting and recordkeeping requirements, Retirement."
        ),
    )


def test_96_1975_reads_the_first_part_printed_in_the_headings_own_paragraph() -> None:
    """``96-1975`` -- the FCC antenna-registration rule prints seventeen
    ``47 CFR Part N`` sub-headings, and the first of them sits in the bare
    heading's OWN paragraph together with its terms, no blank line anywhere.

    Verbatim from the fetched body. Only the paragraphs AFTER the heading
    went through the sub-heading split, so part 0 and its ``Organization and
    functions (Government agencies).`` were dropped with no trace and the
    reading returned sixteen blocks for seventeen printed parts -- the fifth
    silent loss on this route, and the one the structural self-check below
    exists to count rather than discover.
    """

    body = (
        "structure lighting systems are properly maintained. \n\n"
        "List of Subjects\n"
        "47 CFR Part 0\n"
        "    Organization and functions (Government agencies).\n\n"
        "47 CFR Part 1\n\n"
        "    Administrative practice and procedure.\n"
        "47 CFR Part 17\n"
        "    Antennas, Aviation safety, Safety.\n\n"
        "    Federal Communications Commission.\n"
        "William F. Caton,\n"
        "Acting Secretary.\n\n"
    )
    assert extract_blocks_from_text_body(body) == (
        "Organization and functions (Government agencies).",
        "Administrative practice and procedure.",
        "Antennas, Aviation safety, Safety.",
    )


def test_95_16563_skips_agency_labels_between_subject_parts() -> None:
    """Shape F: joint rules label each agency before its CFR parts.

    This is a shortened verbatim excerpt from ``95-16563``. The old strict
    sub-heading/terms alternation read ``OCC`` as a Notice term, reached part
    30, and then stopped at ``Board``. It silently lost five later parts.
    """

    body = (
        "List of Subjects\n\n"
        "OCC\n\n"
        "12 CFR Part 30\n\n"
        "    Administrative practice and procedure, National banks.\n\n"
        "Board\n\n"
        "12 CFR Part 208\n\n"
        "    Accounting, Agriculture, Banks, banking.\n\n"
        "12 CFR Part 263\n\n"
        "    Administrative practice and procedure, Claims.\n\n"
        "FDIC\n\n"
        "12 CFR Part 303\n\n"
        "    Bank deposit insurance, Banks, banking.\n\n"
        "12 CFR Part 308\n\n"
        "    Administrative practice and procedure, Investigations.\n\n"
        "12 CFR Part 364\n\n"
        "    Bank deposit insurance, Safety and soundness.\n\n"
        "OTS\n\n"
        "12 CFR Part 570\n\n"
        "    Accounting, Holding companies, Savings associations.\n\n"
        "DEPARTMENT OF THE TREASURY\n\n"
        "OFFICE OF THE COMPTROLLER OF THE CURRENCY\n\n"
        "Adoption of Final Common Rule\n\n"
        "12 CFR Chapter I\n\n"
        "Authority and Issuance\n"
    )

    assert extract_blocks_from_text_body(body) == (
        "Administrative practice and procedure, National banks.",
        "Accounting, Agriculture, Banks, banking.",
        "Administrative practice and procedure, Claims.",
        "Bank deposit insurance, Banks, banking.",
        "Administrative practice and procedure, Investigations.",
        "Bank deposit insurance, Safety and soundness.",
        "Accounting, Holding companies, Savings associations.",
    )
    assert not unread_subheading_candidate(body)


def test_an_unpunctuated_title_case_term_is_not_an_agency_label() -> None:
    """Shape-F labels must not turn a valid one-term part into decoration."""

    body = (
        "List of Subjects\n\n"
        "OCC\n\n"
        "12 CFR Part 30\n\n"
        "National Banks\n\n"
        "12 CFR Part 31\n\n"
        "Safety.\n\n"
        "Board\n\n"
        "12 CFR Part 208\n\n"
        "Privacy\n\n"
        "12 CFR Part 263\n\n"
        "Administrative practice and procedure.\n"
    )

    assert extract_blocks_from_text_body(body) == (
        "National Banks",
        "Safety.",
        "Privacy",
        "Administrative practice and procedure.",
    )


def test_97_25610_reads_subheadings_below_a_part_naming_heading() -> None:
    """Shape G: the heading names parts and the body repeats each one."""

    body = (
        "List of Subjects in 41 CFR Parts 51-2, 51-4, and 51-6\n\n"
        "41 CFR Part 51-2\n\n"
        "    Organization and functions (Government agencies)\n\n"
        "41 CFR Part 51-4\n\n"
        "    Reporting and recordkeeping requirements.\n\n"
        "41 CFR Part 51-6\n\n"
        "    Government procurement, Handicapped.\n\n"
        "    For the reasons set out in the preamble, parts 51-2, 51-4, "
        "and 51-6 are amended.\n"
    )

    assert extract_blocks_from_text_body(body) == (
        "Organization and functions (Government agencies)",
        "Reporting and recordkeeping requirements.",
        "Government procurement, Handicapped.",
    )
    assert not unread_subheading_candidate(body)


def test_2010_13572_joins_double_spaced_wrapped_terms() -> None:
    """Shape H: the publisher's text rendition blanks every printed line."""

    body = (
        "List of Subjects\n\n\n\n"
        "14 CFR Parts 234, 250, and 259\n\n\n\n"
        "    Air carriers, Consumer protection, Reporting and recordkeeping "
        "\n\nrequirements.\n\n\n\n"
        "14 CFR Part 244\n\n\n\n"
        "    Air carriers, Consumer protection, and Tarmac delay data.\n\n\n\n"
        "14 CFR Part 253\n\n\n\n"
        "    Air carriers, Consumer protection, and Contract of carriage.\n\n\n\n"
        "14 CFR Part 399\n\n\n\n"
        "    Administrative practice and procedure, Air carriers, Air rates "
        "and \n\nfares, Air taxis, Consumer protection, Small businesses.\n\n\n\n"
        "    Issued June 2, 2010 in Washington, DC.\n"
    )

    assert extract_blocks_from_text_body(body) == (
        "Air carriers, Consumer protection, Reporting and recordkeeping requirements.",
        "Air carriers, Consumer protection, and Tarmac delay data.",
        "Air carriers, Consumer protection, and Contract of carriage.",
        (
            "Administrative practice and procedure, Air carriers, Air rates and fares, "
            "Air taxis, Consumer protection, Small businesses."
        ),
    )
    assert not unread_subheading_candidate(body)


def test_a_lowercase_paragraph_after_a_complete_terms_sentence_is_not_joined() -> None:
    """Lower case proves a wrap only while the terms sentence is incomplete."""

    body = (
        "List of Subjects in 40 CFR Part 300\n\n"
        "Safety.\n\n"
        "for the reasons set out in the preamble, part 300 is amended.\n"
    )

    assert extract_blocks_from_text_body(body) == ("Safety.",)


def test_lowercase_amendatory_prose_does_not_extend_an_unpunctuated_term() -> None:
    """An unpunctuated one-term block is complete unless a wrap proves otherwise."""

    body = (
        "List of Subjects in 40 CFR Part 300\n\n"
        "Safety\n\n"
        "for the reasons set out in the preamble, part 300 is amended.\n"
    )

    assert extract_blocks_from_text_body(body) == ("Safety",)


def test_lowercase_amendatory_prose_does_not_extend_a_multi_term_list() -> None:
    """An explicit post-list opening wins even after a comma proves a list."""

    body = (
        "List of Subjects in 40 CFR Part 300\n\n"
        "Safety, Exports\n\n"
        "for the reasons set out in the preamble, part 300 is amended.\n"
    )

    assert extract_blocks_from_text_body(body) == ("Safety, Exports",)


def test_95_11395_joins_a_whole_double_spaced_subject_list() -> None:
    """A wrap may split several ordinary compound labels, not one known pair."""

    body = (
        "List of Subjects in 40 CFR Part 271\n\n"
        "    Administrative practice and\n\n"
        "procedure, Confidential business\n\n"
        "information, Hazardous materials\n\n"
        "transportation, Hazardous waste, Indian\n\n"
        "lands, Intergovernmental relations,\n\n"
        "Penalties, Reporting and recordkeeping\n\n"
        "requirements, Water pollution control,\n\n"
        "Water supply.\n\n"
        "    Authority: 42 U.S.C. 6912(a), 6926, 6974(b).\n"
    )

    assert extract_blocks_from_text_body(body) == (
        (
            "Administrative practice and procedure, Confidential business "
            "information, Hazardous materials transportation, Hazardous waste, Indian "
            "lands, Intergovernmental relations, Penalties, Reporting and recordkeeping "
            "requirements, Water pollution control, Water supply."
        ),
    )


def test_95_30376_does_not_join_an_amendatory_part_heading() -> None:
    """A dangling list conjunction cannot make a printed ``PART`` heading a term."""

    body = (
        "List of Subjects in 49 CFR Part 571\n\n"
        "    Imports, Motor vehicle safety, Motor vehicles, Rubber and\n\n"
        "PART 571--[AMENDED]\n\n"
        "    In consideration of the foregoing, the agency proposes to amend.\n"
    )

    assert extract_blocks_from_text_body(body) == ("Imports, Motor vehicle safety, Motor vehicles, Rubber and",)


def test_the_unread_candidate_path_prepares_the_body_once(monkeypatch) -> None:
    """The census must not strip and scan every large body twice."""

    calls = 0
    original = list_of_subjects.strip_markup

    def counted_strip_markup(payload: str) -> str:
        nonlocal calls
        calls += 1
        return original(payload)

    monkeypatch.setattr(list_of_subjects, "strip_markup", counted_strip_markup)
    body = "List of Subjects\n\n40 CFR Part 300\n\nSafety.\n"

    assert not list_of_subjects.unread_subheading_candidate(body)
    assert calls == 1


def test_95_28471_a_heading_paragraph_without_a_cfr_sub_heading_is_left_alone() -> None:
    """``95-28471`` -- ATF prints its sub-headings as bare ``Part 5``,
    ``Part 19``, with no CFR title, so nothing in the heading's own paragraph
    is a sub-heading this reading recognizes.

    Verbatim from the fetched body. Folding the heading paragraph in anyway
    would read ``Part 5``'s terms and then stop, because ``Part 19 q02`` does
    not end the terms it precedes -- buying six terms by losing the twenty-two
    the publisher printed under part 19. The heading's remainder is therefore
    put through the sub-heading split only when it actually carries one; the
    shape ATF prints here is a different one and is not guessed at.
    """

    body = (
        "List of Subjects\n"
        "Part 5\n"
        "    Advertising, Exports, and Safety.\n"
        "Part 19 q02\n\n"
        "    Administrative practice and procedure, Aircraft, Coal, \n"
        "Exports, Fisheries.\n\n"
        "Part 24\n\n"
        "    Aircraft, Coal.\n\n"
    )
    assert extract_blocks_from_text_body(body) == (
        "Administrative practice and procedure, Aircraft, Coal, Exports, Fisheries.",
    )


def test_printed_sub_headings_are_counted_against_the_blocks_the_reading_returns() -> None:
    """The structural self-check, on the two shapes that decide its verdict.

    ``96-1975`` prints seventeen sub-headings; before the fix the reading
    returned sixteen blocks, which is what a candidate silent loss looks like
    from outside. A block whose part is named in the heading itself prints no
    sub-heading at all, so the count runs the other way and never fires.
    """

    shape_e = (
        "List of Subjects\n"
        "47 CFR Part 0\n"
        "    Organization and functions (Government agencies).\n\n"
        "47 CFR Part 1\n\n"
        "    Administrative practice and procedure.\n\n"
        "    Federal Communications Commission.\n"
    )
    assert printed_cfr_subheadings(shape_e) == ("47 CFR Part 0", "47 CFR Part 1")
    assert len(extract_blocks_from_text_body(shape_e)) == 2
    assert not unread_subheading_candidate(shape_e)

    # A part printed with a sub-heading and no terms under it: two printed,
    # one returned, and the check says so. Nothing is lost here -- there is
    # nothing to lose -- which is why a candidate is read and not counted as
    # a defect.
    no_terms_under_the_first_part = (
        "List of Subjects\n\n"
        "47 CFR Part 0\n\n"
        "47 CFR Part 1\n\n"
        "    Administrative practice and procedure.\n\n"
        "    Federal Communications Commission.\n"
    )
    assert printed_cfr_subheadings(no_terms_under_the_first_part) == (
        "47 CFR Part 0",
        "47 CFR Part 1",
    )
    assert len(extract_blocks_from_text_body(no_terms_under_the_first_part)) == 1
    assert unread_subheading_candidate(no_terms_under_the_first_part)

    heading_names_the_part = "List of Subjects in 40 CFR Part 300\n\n    Exports, Safety.\n\n    Dated: today.\n"
    assert printed_cfr_subheadings(heading_names_the_part) == ()
    assert not unread_subheading_candidate(heading_names_the_part)


def test_the_self_check_stops_before_a_cfr_reference_in_the_amendatory_prose() -> None:
    """``96-21860`` prints ``12 CFR CHAPTER I`` two paragraphs after its block.

    It is a real CFR reference standing alone as a heading, so it counts as a
    printed sub-heading and makes that document a candidate the reading has
    to dismiss by hand. Two paragraphs is the gap the scan allows, because the
    publisher's alternation never puts more than one between two parts; a
    reference further out than that is amendatory furniture and is not
    counted, or every multi-part rule in the corpus would be a candidate.
    """

    body = (
        "List of Subjects\n\n"
        "12 CFR Part 22\n\n    Exports, Safety.\n\n"
        "Office of the Comptroller of the Currency\n\n"
        "12 CFR CHAPTER I\n\n"
        "Authority and Issuance\n\n"
        "    For the reasons set forth in the joint preamble, part 22 is revised.\n\n"
        "PART 22--LOANS IN AREAS HAVING SPECIAL FLOOD HAZARDS\n\n"
        "12 CFR Part 999\n\n"
    )
    assert extract_blocks_from_text_body(body) == ("Exports, Safety.",)
    assert printed_cfr_subheadings(body) == ("12 CFR Part 22", "12 CFR CHAPTER I")
    assert unread_subheading_candidate(body)


def test_a_multi_part_sub_heading_wrapping_over_lines_is_not_cut_in_two() -> None:
    """``95-16287`` -- a sub-heading naming fifteen parts wraps onto further
    lines, and every one of those lines is itself only CFR words, digits and
    commas. Splitting at *any* sub-heading line must still leave a paragraph
    that is a valid sub-heading in full alone, or the alternation reads the
    wrapped tail as this part's terms and loses the real ones.
    """

    body = (
        "List of Subjects\n\n"
        "40 CFR Part 704, 707, 712, 716, 717, 720, 721, 723, 761, 763, 766, 790, \n"
        "795, 796, 799\n\n"
        "    Administrative practice and procedure, Asbestos, Chemicals, \n"
        "Exports, Reporting and recordkeeping requirements, Schools.\n\n"
        "    Authority: 15 U.S.C. 2603\n"
    )
    assert extract_blocks_from_text_body(body) == (
        (
            "Administrative practice and procedure, Asbestos, Chemicals, "
            "Exports, Reporting and recordkeeping requirements, Schools."
        ),
    )


def test_the_notice_shape_has_no_cfr_reference_at_all() -> None:
    """``96-29022`` -- an EPA emergency-exemption Notice prints one anyway."""

    body = (
        "    Authority: 7 U.S.C. 136.\n\nList of Subjects\n\n    Exports, Fisheries.\n\n    Dated: October 30, 1996.\n"
    )
    assert extract_blocks_from_text_body(body) == ("Exports, Fisheries.",)


def test_a_cfr_citation_in_prose_is_not_mistaken_for_a_sub_heading() -> None:
    """``98-19493`` -- ``31 CFR part 700 is revised to read as follows:``.

    It opens with a perfect CFR reference and is a sentence, and reading it
    as a sub-heading would pull the PART heading after it in as terms.
    """

    assert not is_cfr_subheading("31 CFR part 700 is revised to read as follows:")
    assert is_cfr_subheading("15 CFR Parts 771, 773 and 786")
    assert is_cfr_subheading("7 CFR Chapter XXXIV and Part 3402")
    body = (
        "List of Subjects in 31 CFR Part 700\n\n"
        "    Federal buildings and facilities.\n\n"
        "    31 CFR part 700 is revised to read as follows:\n\n"
        "PART 700--REGULATIONS GOVERNING CONDUCT ON THE GROUNDS\n\n"
    )
    assert extract_blocks_from_text_body(body) == ("Federal buildings and facilities.",)


def test_markup_and_entities_are_stripped_before_reading() -> None:
    assert strip_markup('<a href="x">www.gpo.gov</a> &amp; more') == "www.gpo.gov & more"
    assert "alert" not in strip_markup("<script>alert(1)</script>text")


def test_the_plural_heading_is_read_too() -> None:
    """``2010-26684`` prints ``Lists of Subjects``; 5 of 731 sampled bodies do.

    The XML carrier hides this variance because it reads the ``<LSTSUB>``
    element rather than the heading, so it only shows up when the two
    carriers are measured against each other.
    """

    body = "Lists of Subjects in 14 CFR Part 71\n\n    Aircraft, Safety.\n\n    Issued in College Park.\n"
    assert extract_blocks_from_text_body(body) == ("Aircraft, Safety.",)


def test_a_page_break_between_parts_does_not_fuse_them() -> None:
    """``2014-11235`` -- the marker sits after the sentence, not inside it.

    Joining here would glue the finished term list to the next CFR
    sub-heading and end the alternation, losing every part after the page
    break. The character before the marker decides.
    """

    body = (
        "List of Subjects\n\n47 CFR Parts 1 and 2\n\n"
        "    Reporting and recordkeeping requirements.\n\n[[Page 32404]]\n\n"
        "47 CFR Part 27\n\n    Exports, Safety.\n\n"
        "Federal Communications Commission.\n"
    )
    assert extract_blocks_from_text_body(body) == (
        "Reporting and recordkeeping requirements.",
        "Exports, Safety.",
    )


def test_a_body_with_no_block_yields_nothing_rather_than_guessing() -> None:
    """A removal rule deletes a CFR part and prints no List of Subjects."""

    assert extract_blocks_from_xml_body("<RULE><P>Part 12 is removed.</P></RULE>") == ()
    assert extract_blocks_from_text_body("Part 12 is removed.\n\n    Dated: today.\n") == ()
