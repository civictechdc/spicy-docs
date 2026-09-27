"""Retained historical context and explicit abstention, without a new prose grammar."""

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.citations import CitationError, find_citations

FIXTURES = Path(__file__).parent / "fixtures" / "document_citations"


def test_native_inline_historical_context_overrides_document_and_names_its_basis():
    case = json.loads((FIXTURES / "print-inline-congress-2026-09-26.json").read_text())["inline_snippets"][0]
    (finding,) = find_citations(
        case["text"], kinds=("bill_number",), congress=case["covered_congress"], bill_congress_policy="explicit_only"
    )
    assert finding.target_key == "94-sres-400"
    assert finding.target_rule == "bill_number:inline_congress"
    assert case["text"][finding.span_start : finding.span_end] == finding.matched_text


def test_native_subheading_is_distinct_from_document_fallback():
    cases = json.loads((FIXTURES / "print-subheadings-2026-09-26.json").read_text())["subheading_snippets"]
    case = next(c for c in cases if "H.R. 1372" in c["text"])
    found = find_citations(case["text"], kinds=("bill_number",), congress=case["covered_congress"])
    historical = [f for f in found if f.target_key == "115-hr-1372"]
    assert historical and all(f.target_rule == "bill_number:congress_subheading" for f in historical)
    # Native sentence-only input deliberately excludes its governing heading.
    start = case["text"].index("In the 115th Congress, H.R. 1372")
    text = case["text"][start : start + case["text"][start:].index("introduced")]
    (fallback,) = find_citations(text, kinds=("bill_number",), congress=case["covered_congress"])
    (strict,) = find_citations(
        text, kinds=("bill_number",), congress=case["covered_congress"], bill_congress_policy="explicit_only"
    )
    assert fallback.target_rule == "bill_number:document_fallback"
    assert not strict.target_resolved and strict.target_key == "HR1372"
    assert strict.target_rule == "bill_number:document_fallback_refused"
    assert strict.matched_text == fallback.matched_text


def test_explicit_same_congress_keeps_inline_provenance_and_absence_never_uses_clock():
    (same,) = find_citations("H.R. 1 (119th Congress)", kinds=("bill_number",), congress=119)
    assert same.target_rule == "bill_number:inline_congress"
    (missing,) = find_citations("H.R. 1", kinds=("bill_number",))
    assert not missing.target_resolved and missing.target_rule == "bill_number:unstated"
    assert find_citations("transportation and infrastructure funding", bill_congress_policy="explicit_only") == ()
    with pytest.raises(CitationError, match="bill_congress_policy"):
        find_citations("H.R. 1", bill_congress_policy="guess_current")
