"""Distinguish a possessive year from a literal Senate bill citation."""

import pytest

from spicy_docs.interpretation.release_matching import Release, compile_bill_patterns, match_releases
from spicy_docs.sources.congress.bill_status import BillIdentity


@pytest.mark.parametrize("apostrophe", ["'", "’"])
@pytest.mark.parametrize("field", ["title", "excerpt"])
def test_possessive_budget_year_is_not_a_senate_bill(apostrophe, field):
    text = f"the President{apostrophe}s 2027 budget request"
    release = Release("budget", text if field == "title" else "Budget hearing", text if field == "excerpt" else None)
    [match] = match_releases([release], compile_bill_patterns([BillIdentity(119, "s", 2027)]))
    assert match.bill is None
    assert (match.rule, match.matched_field, match.matched_text) == ("unmatched", None, None)


@pytest.mark.parametrize("text", ["S. 2027", "S 2027", "'S. 2027'", "‘S. 2027’"])
def test_real_and_quoted_senate_citations_still_match(text):
    bill = BillIdentity(119, "s", 2027)
    [match] = match_releases([Release("bill", f"Committee considers {text}")], compile_bill_patterns([bill]))
    assert match.bill == bill
    assert (match.rule, match.matched_field) == ("bill_number_in_title", "title")


def test_a_lower_case_designator_is_not_a_senate_citation():
    """``‘s 2027’`` matched only while this module read designators case-insensitively (001).

    The shared bill-number rule it reads through since 002 takes the capital as
    the evidence -- the same fact that refuses ``President's 2027`` -- so a
    quote around a lower-case ``s`` no longer names a bill.
    """
    [match] = match_releases(
        [Release("bill", "Committee considers ‘s 2027’")], compile_bill_patterns([BillIdentity(119, "s", 2027)])
    )
    assert match.bill is None
