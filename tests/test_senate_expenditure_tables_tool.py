"""The committed sidecar against the note that quotes it, and against the print.

`docs/research/senate-expenditure-tables-2026-09-20.md` states counts in prose.
This pins them to the JSON the tool wrote, so a report drifting from the
measurement it cites fails here — the same job
`tests/test_pdf_yield_mods_recheck_tool.py` does for the MODS re-check.

The sidecar is the census over two retained volumes' first 80 pages, produced
by `tools/analysis/senate_expenditure_tables.py` **through the contract's own
classifiers**. That is what keeps the note and the published rows in agreement
— and it is also why one assertion here compares the census against a reader
that shares none of the contract's grammar. An internally consistent census is
what a clean census looks like, so consistency alone is not evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs/research/senate-expenditure-tables-2026-09-20.json"
NOTE = ROOT / "docs/research/senate-expenditure-tables-2026-09-20.md"


def _sidecar() -> dict:
    return json.loads(SIDECAR.read_text())


def test_the_committed_sidecar_states_the_shape_of_the_print() -> None:
    """The four numbers the note's opening paragraph turns on."""
    census = _sidecar()

    assert census["pages"] == 160
    assert census["pages_with_a_table"] == 139
    assert census["tables"] == 139
    # Never two tables on one page, and never one spanning two.
    assert census["tables_per_page"] == {"0": 21, "1": 139}
    assert census["rows"] == 673
    assert census["cells"] == 6172
    assert census["cells_with_no_region"] == 3905


def test_the_committed_sidecar_states_the_three_grids() -> None:
    census = _sidecar()

    assert census["grid_kinds"] == {
        "appropriation_summary": 13,
        "organization_detail": 83,
        "payee_detail": 43,
    }
    assert census["column_counts"] == {"7": 43, "9": 13, "10": 83}
    assert census["geometry_min_rows_columns"] == [3, 7]
    assert census["geometry_max_rows_columns"] == [11, 9]


def test_the_committed_sidecar_states_the_finding_that_shaped_the_contract() -> None:
    """The print rules the summary rows into cells and the payee rows into one.

    This is the measurement the whole design rests on, so it is pinned rather
    than described: were it to change, the case for carrying `cells_json`
    instead of a `payee_name` column changes with it.
    """
    census = _sidecar()
    present = census["entry_row_cells_present_by_grid"]

    assert present["appropriation_summary"] == {"9": 56}
    assert present["organization_detail"] == {"1": 99}
    assert present["payee_detail"] == {"1": 72}
    assert census["row_kinds"]["entry"] == 56 + 99 + 72 == 227


def test_the_contracts_office_count_equals_the_prints() -> None:
    """Two readers, one of which knows nothing of the contract's grammar.

    `table_pages_stating_an_office` is what `page_context` read;
    `table_pages_the_print_states_an_office_on` counts any line beginning
    `Funding Year`, whatever follows. They must agree, and the reason this
    assertion exists is that they once did not: a rule matching only a single
    year read 78 where the print states 83, and the five it lost are the
    Chaplain's multi-year blocks. The census agreed with itself throughout.
    """
    census = _sidecar()

    assert census["table_pages_stating_an_office"] == 83
    assert census["table_pages_the_print_states_an_office_on"] == 83
    assert census["table_pages_with_a_multi_year_funding_span"] == 5
    # Every table page states a printed page label; none is missing.
    assert census["table_pages_stating_a_printed_page"] == census["pages_with_a_table"] == 139


def test_the_committed_sidecar_states_the_amount_totals() -> None:
    census = _sidecar()

    assert census["amounts"] == 1316
    assert census["distinct_amount_spellings"] == 446


def test_the_note_quotes_the_sidecars_own_numbers() -> None:
    """A count in the prose that the measurement does not state is a drifted report."""
    census = _sidecar()
    prose = NOTE.read_text()
    numbers = {int(found.replace(",", "")) for found in re.findall(r"\b\d{1,3}(?:,\d{3})*\b", prose)}

    for stated in (
        census["pages"],
        census["pages_with_a_table"],
        census["rows"],
        census["cells"],
        census["cells_with_no_region"],
        census["amounts"],
        census["row_kinds"]["entry"],
        census["table_pages_stating_an_office"],
        census["table_pages_with_a_multi_year_funding_span"],
        *census["grid_kinds"].values(),
    ):
        assert stated in numbers, f"the note never states {stated}"


def test_the_files_the_census_read_are_the_volumes_the_note_pins() -> None:
    census = _sidecar()
    prose = NOTE.read_text()

    assert sorted(census["files"]) == ["GPO-CDOC-119sdoc3-1.pdf", "GPO-CDOC-119sdoc6-2.pdf"]
    for name, one in census["files"].items():
        assert one["pages"] == 80
        assert name in prose
