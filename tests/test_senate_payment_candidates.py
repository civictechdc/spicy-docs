"""Native B-grid candidates and synthetic fail-closed mutations, not corpus qualification."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from spicy_docs.reading import senate_payment_candidates as reader
from spicy_docs.reading.senate_payment_review import validate_review_sample

pytest.importorskip("pymupdf")
FIXTURES = Path(__file__).parent / "fixtures/senate_expenditures"
BODY = (FIXTURES / "GPO-CDOC-119sdoc6-2.pages11-22.pdf").read_bytes()
TRUTH = json.loads((FIXTURES / "payment-review-2026-09-27.json").read_text())


@pytest.fixture(scope="module")
def parsed():
    return reader.payment_candidates(BODY, pages=[7, 8], source_page_offset=10)


def test_automatic_first_group_matches_manual_truth_and_preserves_provenance(parsed):
    keys = TRUTH["candidate_rows"][0].keys()
    first = [row for row in parsed["candidates"] if row["document"] == "DJST20250194"]
    validate_review_sample(parsed["capture"], TRUTH, [{k: row[k] for k in keys} for row in first])
    assert [row["amount"] for row in first] == ["13.20", "165.89", "291.72"]
    for row in first:
        assert row["office"] == "SENATOR JIM JUSTICE"
        assert row["office_origin_page"] == row["source_page"] == 17
        assert row["printed_page"] == "B-1243" and row["office_word_indices"]
        assert row["header_cells_display"] and row["field_word_indices"]["amount"]
    repeated = [row for row in parsed["candidates"] if row["document"] == "DJST20250202"]
    assert repeated[0]["payee"] == first[0]["payee"] and repeated[0]["line_ordinal"] == 0


def test_summaries_unpriced_text_and_continuation_not_promoted(parsed):
    assert not parsed["publication_qualified"] and parsed["completion_status"] == "partial_not_reconciled"
    assert all(row["page"] == 7 for row in parsed["candidates"])
    assert not any(row["amount"] in {"342.88", "-342.88", "-204348.74"} for row in parsed["candidates"])
    assert any(
        row["reason"] == "office_not_stated_on_page" and row["printed_page"] == "B-1244" for row in parsed["refusals"]
    )
    assert any(row["reason"] == "unpriced_description_attachment_unqualified" for row in parsed["refusals"])
    assert parsed["capture"]["pages"]["8"]["words"][13]["text"] == "CHARLESTON"


@pytest.mark.parametrize("mutation", ["negative", "bad_date", "unknown_document", "office_missing"])
def test_mutated_evidence_refuses_instead_of_borrowing_context(parsed, monkeypatch, mutation):
    capture = deepcopy(parsed["capture"])
    page = capture["pages"]["7"]
    if mutation == "negative":
        page["words"][109]["text"] = "-$13.20"
    elif mutation == "bad_date":
        page["words"][105]["text"] = "02/30/2025"
    elif mutation == "unknown_document":
        page["words"][101]["text"] = "UNKNOWN"
    else:
        page["context"]["office"] = None
    monkeypatch.setattr(reader, "review_pages", lambda *args, **kwargs: capture)
    result = reader.payment_candidates(BODY, pages=[7], source_page_offset=10)
    assert not any(row["document"] == "DJST20250194" for row in result["candidates"])
    assert result["refusals"]


def test_bounds_and_other_grid_refuse():
    with pytest.raises(ValueError, match="bound"):
        reader.payment_candidates(BODY, pages=list(range(1, 10)))
    result = reader.payment_candidates(BODY, pages=[1], source_page_offset=10)
    assert not result["candidates"] and result["pages"][0]["status"] == "unsupported_layout"


SECTION = reader.ReviewedOfficeSection(
    input_sha256="32834f1078045ef2d298cfbe664db9527d0eb39e1557fe9eb656e2ba38e1f7b6",
    first_page=7,
    last_page=9,
    boundary_page=10,
    office="SENATOR JIM JUSTICE",
    funding_year="2025",
)


def test_native_reviewed_section_carries_office_origin_and_stops_before_intern():
    result = reader.payment_candidates(BODY, pages=[7, 8, 9, 10], source_page_offset=10, reviewed_section=SECTION)
    # Native B-1244 and B-1245 explicitly start these document groups. The
    # unpriced CHARLESTON continuation at B-1244's top must not inherit a payee.
    expected = {
        8: ("DJST20250211", "RANDALL R SMITH", "STAFF TRANSPORTATION", "99.40"),
        9: ("DJST20250239", "RYAN D BARDOT", "STAFF PER DIEM", "65.11"),
    }
    for page, values in expected.items():
        rows = [row for row in result["candidates"] if row["page"] == page]
        assert tuple(rows[0][key] for key in ("document", "payee", "description", "amount")) == values
        for row in rows:
            assert row["office"] == "SENATOR JIM JUSTICE"
            assert row["office_origin_page"] == 17
            assert row["office_origin_printed_page"] == "B-1243"
            assert row["office_context_basis"] == "reviewed_contiguous_section"
            assert row["office_word_indices"] == result["candidates"][0]["office_word_indices"]
    assert any(row["page"] == 8 and row["reason"] == "no_qualified_document_group" for row in result["refusals"])
    assert result["pages"][-1]["status"] == "section_boundary"
    assert not any(row["page"] == 10 for row in result["candidates"])
    assert result["publication_qualified"] is False and result["completion_status"] == "partial_not_reconciled"


@pytest.mark.parametrize("change", ["digest", "gap", "boundary", "office"])
def test_reviewed_section_refuses_invalid_proof(change):
    from dataclasses import replace

    section, pages = SECTION, [7, 8, 9, 10]
    if change == "digest":
        section = replace(section, input_sha256="0" * 64)
    elif change == "gap":
        pages = [7, 9, 10]
    elif change == "boundary":
        section = replace(section, last_page=8, boundary_page=9)
        pages = [7, 8, 9]
    else:
        section = replace(section, office="OTHER OFFICE")
    with pytest.raises(ValueError, match="section"):
        reader.payment_candidates(BODY, pages=pages, reviewed_section=section)


def test_reviewed_section_does_not_cross_new_native_heading(monkeypatch):
    capture = reader.review_pages(BODY, pages=[7, 8, 9, 10], source_page_offset=10)
    capture["pages"]["8"]["context"]["office"] = "OTHER OFFICE"
    monkeypatch.setattr(reader, "review_pages", lambda *args, **kwargs: capture)
    with pytest.raises(ValueError, match="new native heading"):
        reader.payment_candidates(BODY, pages=[7, 8, 9, 10], reviewed_section=SECTION)


def test_unsupported_continuation_header_invalidates_later_carry(monkeypatch):
    original = reader._header

    def unsupported(table):
        if any("DJST20250211" in str(cell) for row in table.extract() for cell in row):
            return None
        return original(table)

    monkeypatch.setattr(reader, "_header", unsupported)
    result = reader.payment_candidates(BODY, pages=[7, 8, 9, 10], reviewed_section=SECTION)
    assert result["pages"][1]["status"] == "unsupported_header"
    assert result["pages"][2]["status"] == "unqualified_office_context"
    assert all(row["page"] == 7 for row in result["candidates"])


@pytest.mark.parametrize("change", ["repeated", "below_header"])
def test_office_origin_must_be_printed_once_above_the_header(parsed, monkeypatch, change):
    """The office name counts as printed on the page only as one span above the payment header.

    Synthetic mutations of the native B-1243 capture: the office printed a second time, and the one printing moved
    into the payment body. Either way the page's office is unqualified and nothing on it becomes a candidate.
    """
    capture = deepcopy(parsed["capture"])
    words = capture["pages"]["7"]["words"]
    office = [words[index] for index in (221, 222, 223)]
    if change == "repeated":
        words.extend(deepcopy(office))
    else:
        body_x = words[101]["bbox"]  # DJST20250194, the first payment line
        for word in office:
            word["bbox"] = [body_x[0], word["bbox"][1], body_x[2], word["bbox"][3]]
    monkeypatch.setattr(reader, "review_pages", lambda *args, **kwargs: capture)
    result = reader.payment_candidates(BODY, pages=[7], source_page_offset=10)
    assert not result["candidates"]
    assert [row["reason"] for row in result["refusals"]] == ["office_origin_not_uniquely_above_header"]
    assert result["pages"][0]["status"] == "unqualified_office_context"


@pytest.mark.parametrize(
    ("page", "printed", "message"),
    [("8", "B-1250", "printed pages are not contiguous"), ("7", "1243", "printed B-page continuity")],
)
def test_reviewed_section_needs_consecutive_printed_b_pages(monkeypatch, page, printed, message):
    """A reviewed section's retained pages must print consecutive B-page labels from its origin (synthetic gaps)."""
    capture = reader.review_pages(BODY, pages=[7, 8, 9, 10], source_page_offset=10)
    capture["pages"][page]["context"]["printed_page"] = printed
    monkeypatch.setattr(reader, "review_pages", lambda *args, **kwargs: capture)
    with pytest.raises(ValueError, match=message):
        reader.payment_candidates(BODY, pages=[7, 8, 9, 10], reviewed_section=SECTION)


def test_an_intern_compensation_section_never_carries_its_office(monkeypatch):
    """Intern compensation is refused as a reviewed section even with a native origin and a distinct boundary.

    Synthetic: the native B-1246 heading, INTERN COMPENSATION - JUSTICE, moved to the origin page, and the Senator's
    office to the boundary, so only the intern rule can refuse.
    """
    from dataclasses import replace

    capture = reader.review_pages(BODY, pages=[7, 8, 9, 10], source_page_offset=10)
    intern = capture["pages"]["10"]["context"]["office"]
    assert intern == "INTERN COMPENSATION - JUSTICE"
    capture["pages"]["7"]["context"]["office"] = intern
    capture["pages"]["10"]["context"]["office"] = SECTION.office
    monkeypatch.setattr(reader, "review_pages", lambda *args, **kwargs: capture)
    with pytest.raises(ValueError, match="native origin"):
        reader.payment_candidates(BODY, pages=[7, 8, 9, 10], reviewed_section=replace(SECTION, office=intern))
