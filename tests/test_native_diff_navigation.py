"""Retained printings qualify navigation of additions, removals and renumbered moves."""

from pathlib import Path

import pytest

from spicy_docs.interpretation.section_diff import diff_sections, engine_available
from spicy_docs.sources.congress.bill_tree import parse_bill_tree

pytestmark = pytest.mark.skipif(not engine_available(), reason="requires bill-diff extra")
FIXTURES = Path(__file__).parent / "fixtures/govinfo_bills"


def test_native_hr5334_keeps_added_removed_and_renumbered_endpoint_evidence():
    before = parse_bill_tree((FIXTURES / "text-119hr5334ih.xml").read_bytes(), version="ih")
    after = parse_bill_tree((FIXTURES / "text-119hr5334enr.xml").read_bytes(), version="enr")
    result = diff_sections(before, after, from_version="ih", to_version="enr")
    added = [r for r in result.items if r.op == "added" and not r.to_element_id.startswith("front-matter")]
    removed = [r for r in result.items if r.op == "removed" and not r.from_element_id.startswith("front-matter")]
    assert added and removed
    assert all(r.from_text is None and r.to_text is not None and r.to_element_id for r in added)
    assert all(r.to_text is None and r.from_text is not None and r.from_element_id for r in removed)
    moved = next(r for r in result.items if r.op == "moved")
    assert moved.pairing_rule == "move-round"
    assert moved.from_element_id != moved.to_element_id
    assert moved.from_text.startswith("(b)Effective date")
    assert moved.to_text.startswith("(c)Effective date")
    assert "after December 31, 2024" in moved.from_text
    assert "after December 31, 2025" in moved.to_text
    # A move is the engine's pairing judgment, not unchanged text or legal equivalence.
    assert moved.from_text != moved.to_text
