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
