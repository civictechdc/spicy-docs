"""Selected CC0 unitedstates/citation cases, mapped to our occurrence API.

Source: unitedstates/citation at 953c03d3200080ef3ad85978b46879f9783ba1bb,
test/usc.js, test/cfr.js and test/law.js. The source comments distinguish
publisher-derived examples from synthetic spelling variants. These checks
borrow examples, not upstream's multiple-candidate hyphen policy.
"""

from __future__ import annotations

import pytest

from spicy_docs.interpretation.citation_grammar import (
    find_cfr_citations,
    find_public_law_citations,
    find_usc_citations,
)
from spicy_docs.interpretation.citations import find_citations


@pytest.mark.parametrize(
    ("text", "title", "section", "points", "note"),
    [
        ("5 U.S.C. 552(a)(1)(E)", 5, "552", ("a", "1", "E"), False),
        ("42 U.S.C.285t–2(a)", 42, "285t-2", ("a",), False),
        ("7 U.S.C. 612c note", 7, "612c", (), True),
        ("Section 14123(a)(2) of 49 U.S.C.", 49, "14123", ("a", "2"), False),
    ],
)
def test_usc_occurrences_retain_scope_and_original_spelling(text, title, section, points, note):
    context = f"See {text}; also see {text}."
    found = find_usc_citations(context)
    assert len(found) == 2
    for occurrence in found:
        assert occurrence.text == text
        assert context[occurrence.start : occurrence.end] == text
        assert (occurrence.citation.usc_title, occurrence.citation.usc_section) == (title, section)
        assert occurrence.pinpoint == points
        assert occurrence.citation.usc_note is note
        assert occurrence.refusal is None


@pytest.mark.parametrize(
    ("text", "title", "part", "section", "points"),
    [
        ("14 CFR part 25", 14, "25", None, ()),
        ("48 CFR § 9903.201", 48, "9903", "201", ()),
        ("5CFR, part 575", 5, "575", None, ()),
        ("24 CFR 85.25(h)", 24, "85", "25", ("h",)),
        ("26 CFR § 1.863-3AT", 26, "1", "863-3AT", ()),
    ],
)
def test_cfr_occurrences_retain_coordinates_and_pinpoints(text, title, part, section, points):
    (occurrence,) = find_cfr_citations(text)
    assert occurrence.text == text
    assert (occurrence.citation.cfr_title, occurrence.citation.cfr_part, occurrence.citation.cfr_section) == (
        title,
        part,
        section,
    )
    assert occurrence.pinpoint == points


@pytest.mark.parametrize("text", ["Pub. L. No. 96–164", "Pub L No 96-164", "Public   Law  96–164"])
def test_public_law_spellings(text):
    (occurrence,) = find_public_law_citations(text)
    assert occurrence.citation.public_law == "96-164"
    assert occurrence.text == text


def test_usc_hyphen_is_not_permission_to_invent_additional_sections():
    # The upstream parser emits alternatives for this source example. Our
    # ordering rule retains the complete section token until an edition
    # resolver supplies any stronger evidence.
    (occurrence,) = find_usc_citations("50 U.S.C. 404o-1(a)")
    assert occurrence.citation.usc_section == "404o-1"
    assert occurrence.citation.usc_section_end is None
    assert occurrence.pinpoint == ("a",)


def test_new_spellings_flow_through_versioned_document_citation_rules():
    result = find_citations("Section 14123(a)(2) of 49 U.S.C.; 5CFR, part 575", kinds=("usc_section", "cfr_section"))
    assert {(r.kind, r.target_key, r.target_resolved) for r in result} == {
        ("usc_section", "49-14123", True),
        ("cfr_section", "5-575", True),
    }


@pytest.mark.parametrize("text", ["Section 1 of 49 percent", "Section 1 of 49 U.S.COOKIE", "Section 1\n\nof 49 U.S.C."])
def test_section_first_requires_an_adjacent_code_name(text):
    assert find_usc_citations(text) == ()


def test_comma_after_cfr_title_does_not_donate_prose_numbers():
    (occurrence,) = find_cfr_citations("5 CFR, following 575 comments")
    assert occurrence.citation.cfr_part is None
