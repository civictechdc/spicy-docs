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


def test_same_native_key_and_occurrence_in_different_source_kinds_remain_distinct():
    """A host keyed merge must not silently replace a different source family."""
    from dataclasses import replace

    from spicy_docs.schemas.document_citation_tables import (
        DOCUMENT_CITATIONS,
        DocumentProvenance,
        shape_document_citation,
    )
    from spicy_docs.schemas.tables import digest

    text = "H.R. 1 (119th Congress)"
    (finding,) = find_citations(text, kinds=("bill_number",))
    provenance = DocumentProvenance("shared-key", "govinfo_package", "txt", "literal", digest(text))
    first = shape_document_citation(finding, provenance)
    second = shape_document_citation(finding, replace(provenance, document_kind="comment_inline"))
    assert {key: value for key, value in first.items() if key != "document_kind"} == {
        key: value for key, value in second.items() if key != "document_kind"
    }
    keyed = {DOCUMENT_CITATIONS.key(row): row for row in (first, second)}
    assert len(keyed) == 2
    newer = {**first, "rule_version": "999"}
    keyed[DOCUMENT_CITATIONS.key(newer)] = newer
    assert len(keyed) == 2
    assert keyed[DOCUMENT_CITATIONS.key(second)] == second
    assert keyed[DOCUMENT_CITATIONS.key(first)]["rule_version"] == "999"


def test_a_context_names_no_document_fallback_without_a_congress():
    """An unset basis follows the Congress; one that contradicts it refuses, since target_rule publishes it."""
    from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, CitationContext

    bill = CITATION_RULES_BY_NAME["bill_number"]
    assert bill.target_key("H.R. 7806", CitationContext()) == ("HR7806", False, "bill_number:unstated")
    assert bill.target_key("H.R. 7806", CitationContext(118)) == ("118-hr-7806", True, "bill_number:document_fallback")
    assert CitationContext(congress=118, congress_basis="inline_congress").congress_basis == "inline_congress"
    assert CitationContext(congress_basis="document_fallback_refused").congress_basis == "document_fallback_refused"
    for congress, basis in [
        (None, "document_fallback"),
        (None, "congress_subheading"),
        (118, "unstated"),
        (118, "document_fallback_refused"),
        (118, "caller"),
    ]:
        with pytest.raises(CitationError, match="contradicts"):
            CitationContext(congress=congress, congress_basis=basis)
