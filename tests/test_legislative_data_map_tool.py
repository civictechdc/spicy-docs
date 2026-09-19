"""The legislative data map tool renders its tables from a saved measurement and proves its own claims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis.legislative_data_map import (
    MARK_END,
    MARK_START,
    ROWS,
    TABLES,
    _congress_cells,
    _identity_order,
    _package_id,
    _system_code,
    check_evidence,
    diff_measures,
    render_tables,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs" / "research" / "legislative-data-map-2026-09-18.json"


def test_every_have_or_port_row_names_evidence_that_states_its_claim() -> None:
    check_evidence(ROOT)


def test_render_from_the_saved_measurement_keeps_every_row_and_section() -> None:
    if not SIDECAR.exists():
        pytest.skip("no saved measurement")
    measures = json.loads(SIDECAR.read_text())
    text = render_tables(measures)
    assert text.startswith(MARK_START) and text.endswith(MARK_END)
    for caption in TABLES.values():
        assert f"### {caption}" in text
    body_rows = [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("| Subject")]
    assert sum(1 for line in body_rows if line.count(" | ") == 7) >= len(ROWS)
    if measures.get("comparisons"):
        assert "### Comparisons" in text
    if measures.get("flow"):
        assert "```mermaid" in text and "subgraph unjoined" in text


def test_committee_codes_map_by_rule() -> None:
    assert _system_code("house", "JU00") == "hsju00"
    assert _system_code("senate", "SSAS") == "ssas00"
    assert _system_code("senate", "ssas00") == "ssas00"


def test_package_ids_come_from_congress_gov_and_govinfo_urls() -> None:
    assert _package_id("https://www.congress.gov/119/bills/hr1/BILLS-119hr1enr.htm") == "BILLS-119hr1enr"
    assert (
        _package_id("https://www.govinfo.gov/content/pkg/CHRG-119hhrg63127/pdf/CHRG-119hhrg63127.pdf")
        == "CHRG-119hhrg63127"
    )
    assert _package_id("https://www.congress.gov/119/crec/2026/01/02/171/219/CREC-2026-01-02.pdf") == "CREC-2026-01-02"


def test_identity_names_lead_with_congress_and_session() -> None:
    assert _identity_order(["vote_number", "session", "amendment_number", "congress"])[:3] == [
        "congress",
        "session",
        "vote_number",
    ]


def test_freshness_is_a_floor_when_the_sort_was_ignored() -> None:
    honored = {
        "total": 5,
        "earliest": 115,
        "descentPath": "x/{c}",
        "descentStop": "two-empty",
        "latestUpdate": "2026-09-18",
        "latestSortHonored": True,
    }
    ignored = {**honored, "latestSortHonored": False}
    assert _congress_cells(honored)[0] == "115th Congress+; latest 2026-09-18"
    assert _congress_cells(ignored)[0] == "115th Congress+; updated ≥ 2026-09-18 (sort ignored)"


def test_diff_reports_moved_counts_and_flipped_edges() -> None:
    before = {"congress": {"bill": {"total": 1}}, "flow": {"a→b": {"ok": True}}}
    after = {"congress": {"bill": {"total": 2}}, "flow": {"a→b": {"ok": False}, "c→d": {"ok": True}}}
    lines = diff_measures(before, after)
    assert "congress bill total: 1 → 2" in lines
    assert "edge a→b: resolved → unresolved" in lines
    assert "edge c→d: new, resolved" in lines
    assert diff_measures(after, after) == [
        "no drift in counts, floors, freshness, comparison sets, edge outcomes or sample shapes"
    ]
