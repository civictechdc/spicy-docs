"""The legislative data map tool renders its tables from a saved measurement and proves its own claims."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.analysis.legislative_data_map as data_map_tool
from tools.analysis.legislative_data_map import (
    ERROR_TOLERANCE,
    FLOOR_DESCENT_STEPS,
    FLOOR_EMPTY_TOLERANCE,
    LIST_ROUTES,
    MARK_END,
    MARK_START,
    ROWS,
    TABLES,
    PagedJsonSourceError,
    ProbeUnavailableError,
    _congress_cells,
    _identity_order,
    _package_id,
    _system_code,
    check_evidence,
    diff_measures,
    measure_floors,
    measure_requirements,
    render_tables,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs" / "research" / "legislative-data-map-2026-09-18.json"


def test_every_have_or_port_row_names_evidence_that_states_its_claim() -> None:
    check_evidence(ROOT)


def _replace_row(target: data_map_tool.Row, **changes: object) -> tuple[data_map_tool.Row, ...]:
    """`ROWS` with `target` swapped for a mutated copy, identity-matched (two rows can share text)."""
    mutated = dataclasses.replace(target, **changes)
    return tuple(mutated if row is target else row for row in ROWS)


def test_check_evidence_rejects_a_listing_route_key_not_in_list_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: a `have` row citing `congress/listing.py` for a route LIST_ROUTES does not have must fail."""
    target = next(row for row in ROWS if row.data == "Enacted bills list")
    assert target.status == "have" and data_map_tool.LISTING_MODULE in target.evidence
    assert "not-a-real-route" not in LIST_ROUTES
    monkeypatch.setattr(data_map_tool, "ROWS", _replace_row(target, measure=(target.measure[0], "not-a-real-route")))
    with pytest.raises(SystemExit):
        check_evidence(ROOT)


def test_check_evidence_rejects_a_symbol_not_defined_in_its_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: a `have` row naming a function its evidence file never defines must fail."""
    target = next(row for row in ROWS if row.data == "Senate per-vote XML")
    assert target.status == "have"
    monkeypatch.setattr(data_map_tool, "ROWS", _replace_row(target, note=target.note + " via `totally_fake_helper_fn`"))
    with pytest.raises(SystemExit):
        check_evidence(ROOT)


def test_check_evidence_passes_a_real_listing_route_and_a_real_symbol() -> None:
    """The positive case behind the two mutation checks above: today's rows name real things."""
    senate_vote = next(row for row in ROWS if row.data == "Senate per-vote XML")
    assert set(data_map_tool._note_symbols(senate_vote.note)) >= {
        "SenateVoteMenuAcquisition",
        "VoteAcquirer",
        "list_senate_votes",
    }
    law = next(row for row in ROWS if row.data == "Enacted bills list")
    assert law.measure[1] in LIST_ROUTES
    check_evidence(ROOT)  # does not raise


class _FakeFamily:
    name = "congress-gov"


class _FakeFloorsReader:
    """Enough of `PagedJsonReader` for `_count()`: `.family.name` and `.page(url, *, records_key)`."""

    family = _FakeFamily()

    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)

    def page(self, url: str, *, records_key: object) -> SimpleNamespace:
        value = next(self._responses)
        if isinstance(value, BaseException):
            raise value
        return SimpleNamespace(declared_count=value, records=())


def _floors(earliest: int, responses: list[object]) -> dict:
    measures: dict = {"congress": {"treaty": {"earliest": earliest}}}
    measure_floors(_FakeFloorsReader(responses), measures, api_key="k3y-test")
    return measures["congress"]["treaty"]


def test_measure_floors_stop_cap_when_the_walk_never_finds_a_real_empty_run() -> None:
    facts = _floors(70, [1] * FLOOR_DESCENT_STEPS)
    assert facts["descentStop"] == "cap"
    assert facts["earliest"] == 70 - 1 - (FLOOR_DESCENT_STEPS - 1)
    assert "floorGap" not in facts


def test_measure_floors_stop_floor_when_the_walk_reaches_the_1st_congress() -> None:
    facts = _floors(10, [1] * 9)
    assert facts["descentStop"] == "floor"
    assert facts["earliest"] == 1
    assert "floorGap" not in facts


def test_measure_floors_stop_empty_run_after_the_tolerated_streak_of_empties() -> None:
    facts = _floors(100, [1, 1] + [0] * FLOOR_EMPTY_TOLERANCE)
    assert facts["descentStop"] == "empty-run"
    assert facts["earliest"] == 98
    assert "floorGap" not in facts


def test_measure_floors_stop_error_after_the_tolerated_streak_of_publisher_errors() -> None:
    facts = _floors(20, [1, 1] + [PagedJsonSourceError("boom")] * ERROR_TOLERANCE)
    assert facts["descentStop"] == "error"
    assert facts["earliest"] == 18
    assert facts["belowFloor"][12] is None
    assert "floorGap" not in facts


def test_measure_floors_pops_a_stale_floor_gap_field_from_an_earlier_run() -> None:
    """A sidecar written by the tool before floorGap was removed still carries the field; a new run drops it."""
    measures = {"congress": {"treaty": {"earliest": 10, "floorGap": [3]}}}
    measure_floors(_FakeFloorsReader([1] * 9), measures, api_key="k3y-test")
    assert "floorGap" not in measures["congress"]["treaty"]


class _FakeRequirementsReader:
    """Enough of `PagedJsonReader` for `_walk()` and `_cg()`: `.pages()` and `.capture_validated()`."""

    family = _FakeFamily()

    def __init__(self, list_pages: list[list[dict]], detail_responses: list[object]) -> None:
        self._list_pages = list(list_pages)
        self._detail_responses = iter(detail_responses)
        self.asked: list[str] = []

    def pages(self, url: str, *, records_key: str, max_pages: int) -> object:
        for records in self._list_pages:
            yield SimpleNamespace(records=records)

    def capture_validated(self, url: str, **_kwargs: object) -> tuple[object, None]:
        self.asked.append(url)
        value = next(self._detail_responses)
        if isinstance(value, BaseException):
            raise value
        return value, None


def test_measure_requirements_histograms_rows_and_pins_the_detail_floor() -> None:
    def row(congress: int, number: int, *, stated: bool = False) -> dict:
        entry = {"congress": congress, "communicationType": {"code": "EC"}, "number": number}
        if stated:
            # The publisher spells its own locator upper-case; the probe must ask it verbatim.
            entry["url"] = f"https://api.congress.gov/v3/house-communication/{congress}/EC/{number}?format=json"
        return entry

    list_pages = [
        [row(105, 1, stated=True), row(105, 2)],
        [row(106, 3), row(106, 4), row(106, 5)],
        [row(107, 6)],
    ]
    detail_responses = [
        ProbeUnavailableError(SimpleNamespace(status_code=404)),  # 105: first row (EC 1) has no detail record
        {"houseCommunication": {"number": 3}},  # 106: first row (EC 3) resolves
        {"houseCommunication": {"number": 6}},  # 107: resolves too, but the floor is already set at 106
    ]
    reader = _FakeRequirementsReader(list_pages, detail_responses)
    result = measure_requirements(reader, api_key="k3y-test")
    assert result["total"] == 6
    assert result["histogram"] == {"105": 2, "106": 3, "107": 1}
    assert result["detailFloor"] == 106
    assert result["coveredByFloor"] == 4
    assert result["share"] == pytest.approx(4 / 6)
    assert result["detail"]["105"] == {
        "sampled": True,
        "resolved": False,
        "label": "105th EC 1",
        "locator": "publisher",
        "error": "HTTP 404",
    }
    assert reader.asked[0] == "https://api.congress.gov/v3/house-communication/105/EC/1?format=json"
    assert result["detail"]["106"] == {
        "sampled": True,
        "resolved": True,
        "label": "106th EC 3",
        "locator": "constructed",
    }
    assert reader.asked[1] == "https://api.congress.gov/v3/house-communication/106/ec/3?format=json"
    assert result["detail"]["108"] == {"sampled": False}


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


def test_committed_map_and_sidecar_match_the_current_rows() -> None:
    measures = json.loads(SIDECAR.read_text())
    assert measures["rows"] == json.loads(json.dumps([dataclasses.asdict(row) for row in ROWS]))
    committed = SIDECAR.with_suffix(".md").read_bytes()
    start = committed.index(MARK_START.encode())
    end = committed.index(MARK_END.encode()) + len(MARK_END.encode())
    assert committed[start:end] == render_tables(measures).encode()


def test_offline_refresh_updates_judgments_without_remeasuring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_request(*_args: object, **_kwargs: object) -> None:
        pytest.fail("offline refresh must not initialize a network reader")

    for reader in ("CongressListingReader", "GovInfoDiscoveryReader", "KeylessProbe"):
        monkeypatch.setattr(data_map_tool, reader, unexpected_request)
    original = json.loads(SIDECAR.read_text())
    original["rows"] = [{"status": "stale"}]
    output = tmp_path / "map.json"
    output.write_text(json.dumps(original))
    document = tmp_path / "map.md"
    document.write_text(f"before\n{MARK_START}\nstale\n{MARK_END}\nafter\n")
    args = ["--offline", "--output", str(output), "--map", str(document)]

    assert data_map_tool.main(args) == 0
    refreshed = json.loads(output.read_text())
    assert refreshed.pop("rows") == json.loads(json.dumps([dataclasses.asdict(row) for row in ROWS]))
    original.pop("rows")
    assert refreshed == original  # Counts, dates, revision and retained evidence stay measured facts.
    assert document.read_text() == f"before\n{render_tables(refreshed)}\nafter\n"

    first = output.read_bytes(), document.read_bytes()
    assert data_map_tool.main(args) == 0
    assert (output.read_bytes(), document.read_bytes()) == first


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
