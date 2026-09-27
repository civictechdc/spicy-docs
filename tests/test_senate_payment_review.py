"""Native positional truth set; successful comparison is not payment publication."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from spicy_docs.reading.senate_payment_review import review_pages, validate_review_sample

pytest.importorskip("pymupdf")
FIXTURES = Path(__file__).parent / "fixtures/senate_expenditures"
TRUTH = json.loads((FIXTURES / "payment-review-2026-09-27.json").read_text())


@pytest.fixture(scope="module")
def capture():
    return review_pages(
        (FIXTURES / "GPO-CDOC-119sdoc6-2.pages11-22.pdf").read_bytes(), pages=[7, 8], source_page_offset=10
    )


def test_native_sample_retains_raw_blocks_and_positions(capture):
    validate_review_sample(capture, TRUTH, TRUTH["candidate_rows"])
    first, second = capture["pages"]["7"], capture["pages"]["8"]
    assert first["context"]["office"] == "SENATOR JIM JUSTICE"
    assert second["context"]["office"] is None
    assert first["tables"] and second["tables"]
    assert all(len(word["bbox"]) == 4 for page in capture["pages"].values() for word in page["words"])
    # Repeated payees are distinct source groups, not a unique payment key.
    seen = {item["id"]: item["literal"] for item in TRUTH["observations"]}
    assert seen["first_payee"] == seen["repeat_payee"] == "ERAJ SHIRVANI"
    assert seen["first_document"] != seen["repeat_document"]
    assert seen["unresolved_page_leading_description"] == "CHARLESTON TO MARTINSBURG AND RETURN"
    assert len(TRUTH["candidate_rows"]) == 3


@pytest.mark.parametrize("mutation", ["digest", "mapping", "literal", "negative_index", "decimal"])
def test_truth_gate_refuses_evidence_drift(capture, mutation):
    truth = deepcopy(TRUTH)
    if mutation == "digest":
        truth["input_sha256"] = "0" * 64
    elif mutation == "mapping":
        truth["pages"]["7"]["source_page"] = 7
    elif mutation == "literal":
        truth["observations"][0]["literal"] = "DUST20250194"
    elif mutation == "negative_index":
        truth["observations"][0]["word_indices"] = [-1]
    else:
        next(item for item in truth["observations"] if "decimal" in item)["decimal"] = "13.21"
    with pytest.raises(ValueError):
        validate_review_sample(capture, truth, truth["candidate_rows"])


@pytest.mark.parametrize("mutation", ["collapse", "zip", "float", "extra"])
def test_candidate_gate_refuses_lossy_or_invented_payment_rows(capture, mutation):
    rows = deepcopy(TRUTH["candidate_rows"])
    if mutation == "collapse":
        rows.pop()
    elif mutation == "zip":
        rows[1]["payee"] = "CAROLINE S JAMES"
    elif mutation == "float":
        rows[0]["amount"] = 13.2
    else:
        rows.append(dict(rows[0], line_ordinal=3))
    with pytest.raises(ValueError, match="candidate payment"):
        validate_review_sample(capture, TRUTH, rows)
