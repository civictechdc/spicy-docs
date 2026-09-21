"""The thirty-six bill-identify cases from BillTrax, ported to the pure scorer.

Pins number, title, sponsor, congress and section-heading extraction from bill
text, weighted confidence scoring with its sealed thresholds and five-result
cap, and the port's own invariants: the five weights sum to one and heading
comparisons are bounded to three candidates.
"""

from spicy_docs.interpretation.bill_signals import (
    IDENTIFY_CONFIDENCE_THRESHOLDS,
    MAX_HEADING_COMPARISONS,
    SIGNAL_WEIGHTS,
    CandidateBill,
    extract_signals,
    identify_bill,
)

FIXTURE_BILL = CandidateBill(
    bill_id="bill-uuid-7148",
    congress=119,
    bill_type="HR",
    number="7148",
    title="Making appropriations for the Department of Defense for the fiscal year ending September 30 2025",
    short_title="Department of Defense Appropriations Act 2025",
    sponsor="Mr. CARTER",
    section_headings=("Short Title", "Definitions"),
)


def signal(match, name):
    return next((entry for entry in match.signals if entry.name == name), None)


# --- extractSignals: bill number extraction (6 cases) ---


def test_parses_h_r_7148() -> None:
    """``H.R. 7148`` parses as type ``HR``, number ``7148``."""
    signals = extract_signals("H.R. 7148 - Making appropriations")
    assert (signals.bill_type, signals.bill_number) == ("HR", "7148")


def test_parses_h_space_r_7148() -> None:
    """``H. R.`` with a space between the letters parses as ``HR``."""
    signals = extract_signals("H. R. 7148 - Making appropriations")
    assert (signals.bill_type, signals.bill_number) == ("HR", "7148")


def test_parses_gpo_bullet_form() -> None:
    """The GPO bullet form ``•HR  7148  IH`` parses as ``HR`` 7148."""
    signals = extract_signals("•HR  7148  IH\nMaking appropriations for defense")
    assert (signals.bill_type, signals.bill_number) == ("HR", "7148")


def test_parses_senate_bill() -> None:
    """``S. 998`` parses as type ``S``."""
    signals = extract_signals("S. 998 - An act to authorize")
    assert (signals.bill_type, signals.bill_number) == ("S", "998")


def test_parses_house_joint_resolution() -> None:
    """``H.J.Res. 42`` parses as type ``HJRES``."""
    signals = extract_signals("H.J.Res. 42 - Joint resolution")
    assert (signals.bill_type, signals.bill_number) == ("HJRES", "42")


def test_no_bill_number_pattern() -> None:
    """Text with no bill-number pattern yields no type or number."""
    signals = extract_signals("This document has no bill number in it.")
    assert (signals.bill_type, signals.bill_number) == (None, None)


# --- extractSignals: title extraction (12 cases) ---


def test_title_after_a_bill_marker() -> None:
    """The title following an ``A BILL`` marker is captured and normalized."""
    text = "H.R. 7148\n\nA BILL\n\nTo make appropriations for the Department of Defense\n\nSECTION 1."
    assert "appropriations" in (extract_signals(text).normalized_title or "")


def test_title_after_an_act_marker() -> None:
    """The title following an ``AN ACT`` marker is captured and normalized."""
    text = "S. 101\n\nAN ACT\n\nTo authorize programs of the Department of Energy\n\nSECTION 1."
    assert "authorize" in (extract_signals(text).normalized_title or "")


def test_falls_back_to_chars_200_to_600() -> None:
    """With no title marker, the character-200-to-600 window supplies a title."""
    signals = extract_signals("x" * 200 + "appropriations defense homeland security title")
    assert signals.normalized_title
    assert len(signals.normalized_title) > 0


def test_text_shorter_than_the_fallback_window() -> None:
    """Text too short for the fallback window yields no title."""
    assert extract_signals("Short text").normalized_title is None


def test_tier_a_doubled_single_quote() -> None:
    """A ``may be cited as`` title in doubled single quotes is captured."""
    signals = extract_signals("H.R. 7148\nThis Act may be cited as the ''Consolidated Appropriations Act, 2026''.")
    assert "consolidated appropriations act" in (signals.normalized_title or "")
    assert signals.title_source == "may-be-cited-as"


def test_tier_a_ascii_double_quote() -> None:
    """A ``may be cited as`` title in ASCII double quotes is captured."""
    signals = extract_signals('H.R. 100\nThis Act may be cited as the "Defense Authorization Act, 2025".')
    assert "defense authorization act" in (signals.normalized_title or "")
    assert signals.title_source == "may-be-cited-as"


def test_tier_a_single_quote() -> None:
    """A ``may be cited as`` title in single quotes is captured."""
    signals = extract_signals("H.R. 200\nThis Act may be cited as the 'Healthcare Reform Act'.")
    assert "healthcare reform act" in (signals.normalized_title or "")
    assert signals.title_source == "may-be-cited-as"


def test_tier_a_typographic_quotes() -> None:
    """A ``may be cited as`` title in typographic quotes is captured."""
    signals = extract_signals("H.R. 300\nThis Act may be cited as the “Environmental Protection Act”.")
    assert "environmental protection act" in (signals.normalized_title or "")
    assert signals.title_source == "may-be-cited-as"


def test_tier_a_backticks() -> None:
    """A ``may be cited as`` title in backticks is captured."""
    signals = extract_signals("H.R. 400\nThis Act may be cited as the `Infrastructure Investment Act`.")
    assert "infrastructure investment act" in (signals.normalized_title or "")
    assert signals.title_source == "may-be-cited-as"


def test_title_source_fallback_marker() -> None:
    """A title found after a bill/act marker reports source ``fallback-marker``."""
    text = "H.R. 500\n\nA BILL\n\nTo provide for something useful.\n\nBe it enacted"
    assert extract_signals(text).title_source == "fallback-marker"


def test_title_source_fallback_position() -> None:
    """A title found in the fallback window reports source ``fallback-position``."""
    signals = extract_signals("x" * 200 + "some title text here without any markers")
    assert signals.title_source == "fallback-position"


def test_title_source_none() -> None:
    """A document with no title reports source ``none``."""
    assert extract_signals("H.R. 1").title_source == "none"


# --- extractSignals: sponsor extraction (6 cases) ---


def test_sponsor_standard_format() -> None:
    """``Mr. JOHNSON of Texas`` extracts sponsor last name ``JOHNSON``."""
    signals = extract_signals("H.R. 1234\nMr. JOHNSON of Texas introduced the following bill")
    assert signals.sponsor_last_name == "JOHNSON"


def test_sponsor_ms_honorific() -> None:
    """``Ms.`` is accepted as an honorific and ``PELOSI`` extracted."""
    signals = extract_signals("H.R. 10 - A bill\nMs. PELOSI of California introduced the following bill")
    assert signals.sponsor_last_name == "PELOSI"


def test_sponsor_small_caps_split() -> None:
    """A line break inside a small-caps surname still extracts ``COLE``."""
    signals = extract_signals("H.R. 7148\nMr. C\nOLE introduced the following bill")
    assert signals.sponsor_last_name == "COLE"


def test_sponsor_run_on() -> None:
    """``COLEintroduced`` with no space still extracts ``COLE``."""
    signals = extract_signals("H.R. 7148\nMr. COLEintroduced the following bill")
    assert signals.sponsor_last_name == "COLE"


def test_sponsor_normal_spacing() -> None:
    """Normal spacing extracts ``COLE``."""
    signals = extract_signals("H.R. 7148\nMr. COLE introduced the following bill")
    assert signals.sponsor_last_name == "COLE"


def test_no_sponsor_line() -> None:
    """A bill with no sponsor line yields no sponsor."""
    assert extract_signals("H.R. 1234 - A bill to do things").sponsor_last_name is None


# --- extractSignals: congress extraction (3 cases) ---


def test_congress_with_ordinal() -> None:
    """``119th Congress`` extracts congress 119."""
    assert extract_signals("119th Congress, 1st Session\nH.R. 1").congress == 119


def test_congress_without_ordinal() -> None:
    """``118 Congress`` without an ordinal extracts 118."""
    assert extract_signals("118 Congress\nH.R. 9").congress == 118


def test_no_congress_marker() -> None:
    """A document with no congress marker yields no congress."""
    assert extract_signals("H.R. 1234 - A bill").congress is None


# --- extractSignals: section headings (2 cases) ---


def test_extracts_up_to_five_section_headings() -> None:
    """At most five section headings are extracted, normalized to lowercase."""
    text = (
        "H.R. 1\n"
        "SECTION 1. SHORT TITLE.\n"
        "SECTION 2. DEFINITIONS.\n"
        "SECTION 3. AUTHORIZATION.\n"
        "SECTION 4. APPROPRIATIONS.\n"
        "SECTION 5. EFFECTIVE DATE.\n"
        "SECTION 6. SUNSET."
    )
    signals = extract_signals(text)
    assert len(signals.section_headings) == 5
    assert "short title" in signals.section_headings[0]


def test_no_section_headings() -> None:
    """Text without section markers yields no headings."""
    assert extract_signals("H.R. 1 - Some text without sections").section_headings == ()


# --- identifyBill: empty text (2 cases) ---


def test_empty_text_identifies_nothing() -> None:
    """Empty text identifies no bill."""
    assert identify_bill(extract_signals(""), (FIXTURE_BILL,)) == ()


def test_whitespace_only_text_identifies_nothing() -> None:
    """Whitespace-only text identifies no bill."""
    assert identify_bill(extract_signals("   \n  "), (FIXTURE_BILL,)) == ()


# --- identifyBill: confidence scoring (4 cases) ---


def test_matching_number_title_and_congress_scores_high() -> None:
    """A matching number, congress and two headings score at least the medium threshold."""
    text = (
        "119th Congress, 1st Session\n"
        "H.R. 7148 - Making appropriations for the Department of Defense\n"
        "\n"
        "A BILL\n"
        "\n"
        "Making appropriations for the Department of Defense for the fiscal year ending September 30 2025\n"
        "\n"
        "SECTION 1. SHORT TITLE.\n"
        "SECTION 2. DEFINITIONS."
    )
    matches = identify_bill(extract_signals(text), (FIXTURE_BILL,))
    assert matches
    top = matches[0]
    assert (top.bill_id, top.bill_type, top.number) == ("bill-uuid-7148", "HR", "7148")
    assert top.confidence >= IDENTIFY_CONFIDENCE_THRESHOLDS["medium"]
    assert signal(top, "bill_number").score == 1
    assert signal(top, "congress").score == 1
    assert signal(top, "section_heading_overlap").matched == 2


def test_no_candidates_identifies_nothing() -> None:
    """An empty candidate list yields no matches."""
    assert identify_bill(extract_signals("H.R. 9999 - 119th Congress\nA BILL\nTo do something"), ()) == ()


def test_candidates_below_the_floor_are_dropped() -> None:
    """Matches scoring below the confidence floor are dropped."""
    poor = CandidateBill(
        bill_id="bill-uuid-s1",
        congress=119,
        bill_type="S",
        number="1",
        title="An act about something entirely different",
    )
    matches = identify_bill(extract_signals("H.R. 7148 - Making appropriations\n119th Congress"), (poor,))
    assert all(match.confidence >= 0.1 for match in matches)


def test_at_most_five_results() -> None:
    """At most five candidates are returned."""
    candidates = tuple(
        CandidateBill(
            bill_id=f"bill-uuid-{index}",
            congress=110 + index,
            bill_type=FIXTURE_BILL.bill_type,
            number=FIXTURE_BILL.number,
            title=FIXTURE_BILL.title,
            short_title=FIXTURE_BILL.short_title,
            sponsor=FIXTURE_BILL.sponsor,
        )
        for index in range(10)
    )
    text = "H.R. 7148 - 119th Congress\nA BILL\nMaking appropriations"
    assert len(identify_bill(extract_signals(text), candidates)) <= 5


# --- thresholds (1 case) ---


def test_thresholds_are_the_sealed_values() -> None:
    """The high and medium thresholds keep their sealed values."""
    assert IDENTIFY_CONFIDENCE_THRESHOLDS["high"] == 0.85
    assert IDENTIFY_CONFIDENCE_THRESHOLDS["medium"] == 0.55


# --- the port's own invariants ---


def test_the_five_weights_sum_to_one() -> None:
    """The five signal weights sum to exactly one."""
    assert round(sum(SIGNAL_WEIGHTS.values()), 10) == 1.0


def test_heading_overlap_is_bounded_to_three_candidates() -> None:
    """Only ``MAX_HEADING_COMPARISONS`` candidates are scored on heading overlap."""
    candidates = tuple(
        CandidateBill(
            bill_id=f"bill-{index}",
            congress=119,
            bill_type="HR",
            number="7148",
            title=FIXTURE_BILL.title,
            section_headings=("Short Title",),
        )
        for index in range(6)
    )
    text = "H.R. 7148\n119th Congress\nSECTION 1. SHORT TITLE."
    matches = identify_bill(extract_signals(text), candidates)
    scored = sum(signal(match, "section_heading_overlap") is not None for match in matches)
    assert scored == MAX_HEADING_COMPARISONS
