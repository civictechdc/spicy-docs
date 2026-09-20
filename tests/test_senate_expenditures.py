"""The Secretary of the Senate's ruled tables, read from two bounded page ranges.

The fixtures are real page ranges cut out of two retained volumes, not
excerpts: ``tests/fixtures/senate_expenditures/README.md`` states the
provenance, and the cut reads text and cells identically to the volume it came
from, page for page.

What this module owns: the measured facts about the print (which grid is
where, what a ruled row is, where the office and the page label are stated),
the falsifiable totals check, and the shaped rows the generic contract loop in
``tests/test_table_contracts.py`` runs over.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.senate_expenditure_tables import (
    SENATE_EXPENDITURE_RULE_VERSION,
    grid_kind,
    page_context,
    parse_amount,
    shape_senate_expenditure_rows,
    summary_totals,
    table_period,
)
from spicy_docs.schemas.tables import Row, digest, read_json_column

pytest.importorskip("pymupdf", reason="needs the 'pdf' extra: uv sync --extra pdf")

FIXTURES = Path(__file__).parent / "fixtures/senate_expenditures"

#: The whole SUMMARY OF TRANSACTIONS BY APPROPRIATIONS section of Part I of the
#: 119th Congress's first report, A-1 to A-7, ending on the print's own Totals
#: row.  The one fixture that makes the totals check runnable.
SUMMARY_ONLY = "GPO-CDOC-119sdoc3-1.pages11-17.pdf"
#: A second whole summary section from the other volume and the other reporting
#: period, plus the first six pages of its detailed statement: the other two
#: grids, one office block and its continuation pages.
BOTH_GRIDS = "GPO-CDOC-119sdoc6-2.pages11-22.pdf"

_SOURCES = {one["fixture"]: one for one in json.loads((FIXTURES / "sources.json").read_text())}


@cache
def pages_for(fixture: str):
    """Every ``PageResult`` of one fixture, read once per session with ``tables=True``."""
    from spicy_docs.extraction.api import DocumentExtractor, NativeText

    source = (FIXTURES / fixture).read_bytes()
    extractor = DocumentExtractor(NativeText(), tables=True)
    return tuple(extractor.extract(source, media_type="application/pdf"))


@cache
def rows_for(fixture: str) -> tuple[Row, ...]:
    """Every shaped row of one fixture.

    ``page_count`` and ``pages_read`` are the *volume's*, not the cut's: these
    pages were read out of a 1,335- and a 1,264-page print, which is what makes
    every count taken over these rows a floor and ``pages_capped`` true.
    """
    source = _SOURCES[fixture]
    first, last = source["pages"]
    out: list[Row] = []
    for result in pages_for(fixture):
        context = page_context(result.text)
        for ordinal, table in enumerate(result.tables):
            out.extend(
                shape_senate_expenditure_rows(
                    table,
                    result.text,
                    package_id=source["package_id"],
                    file_name=source["source_file"],
                    table_ordinal=ordinal,
                    page_count=source["source_page_count"],
                    pages_read=last - first + 1,
                    body_rendition="pdf",
                    body_derivation="pdf-extraction-lines",
                    context=context,
                )
            )
    return tuple(out)


def identities_for(fixture: str) -> tuple[tuple[str, ...], ...]:
    """Each row's identity rebuilt from the extraction, never read back out of the row.

    The page, the table ordinal and the row ordinal are walked from the
    ``PageResult`` stream and the digest is taken from the page text here, so a
    shaper that mis-keyed a row fails rather than agreeing with itself.
    """
    source = _SOURCES[fixture]
    out: list[tuple[str, ...]] = []
    for result in pages_for(fixture):
        page_digest = digest(result.text)
        for ordinal, table in enumerate(result.tables):
            for row_ordinal in range(table.row_count):
                out.append(
                    (
                        source["package_id"],
                        source["source_file"],
                        str(result.metadata["page"]),
                        str(ordinal),
                        str(row_ordinal),
                        page_digest,
                    )
                )
    return tuple(out)


# ---------------------------------------------------------------------------
# What the print actually is, pinned.
# ---------------------------------------------------------------------------


#: Measured 2026-09-20 over 160 pages of these two volumes and reproduced here
#: over the 19 committed ones.  Receipt:
#: ``~/Work/corpora/supply-2026-09-02/receipts/senate-expenditure-tables-2026-09-20/``.
MEASURED = {
    SUMMARY_ONLY: {"pages": 7, "tables": 7, "rows": 43},
    BOTH_GRIDS: {"pages": 12, "tables": 12, "rows": 71},
}


@pytest.mark.parametrize("fixture", sorted(MEASURED))
def test_every_page_carries_exactly_one_ruled_table(fixture: str) -> None:
    """139 of 139 sampled pages carried one table; never two, never one spanning two."""
    pages = pages_for(fixture)
    assert len(pages) == MEASURED[fixture]["pages"]
    assert [len(page.tables) for page in pages] == [1] * len(pages)
    assert sum(len(page.tables) for page in pages) == MEASURED[fixture]["tables"]
    assert len(rows_for(fixture)) == MEASURED[fixture]["rows"]


def test_the_print_draws_three_grids_and_the_first_row_says_which() -> None:
    kinds = [grid_kind(table) for fixture in MEASURED for page in pages_for(fixture) for table in page.tables]
    assert kinds.count("appropriation_summary") == 13
    assert kinds.count("organization_detail") == 3
    assert kinds.count("payee_detail") == 3
    assert None not in kinds


def test_the_measured_geometry_is_what_these_pages_carry() -> None:
    """The rollup pinned rows 3/5/11 and columns 7/10 min to max over 480 pages."""
    shapes = [
        (table.row_count, table.column_count)
        for fixture in MEASURED
        for page in pages_for(fixture)
        for table in page.tables
    ]
    assert min(rows for rows, _ in shapes) == 3
    assert max(rows for rows, _ in shapes) == 11
    assert sorted({columns for _, columns in shapes}) == [7, 9, 10]


def test_the_print_rules_the_summary_rows_and_not_the_payee_rows() -> None:
    """The decisive measurement: a payee line is a line inside one cell, not a ruled row.

    Every ``appropriation_summary`` entry row has all nine cells; every
    ``organization_detail`` and ``payee_detail`` entry row has exactly one.
    This is why the contract carries no ``payee_name`` or ``amount`` column.
    """
    ruled_by_grid: dict[str, set[bool]] = {}
    for fixture in MEASURED:
        for row in rows_for(fixture):
            if row["row_kind"] != "entry":
                continue
            ruled_by_grid.setdefault(row["grid_kind"], set()).add(row["cells_ruled"] == "true")
    assert ruled_by_grid["appropriation_summary"] == {True}
    assert ruled_by_grid["organization_detail"] == {False}
    assert ruled_by_grid["payee_detail"] == {False}
    for row in rows_for(BOTH_GRIDS):
        if row["row_kind"] == "entry" and row["grid_kind"] != "appropriation_summary":
            assert sum(1 for cell in read_json_column(row["cells_json"]) if cell is not None) == 1


def test_the_governing_header_band_is_the_nearest_one_and_not_the_first() -> None:
    """An organization_detail table has two bands; column 0 changes role between them."""
    table = next(
        table for page in pages_for(BOTH_GRIDS) for table in page.tables if grid_kind(table) == "organization_detail"
    )
    rows = [row for row in rows_for(BOTH_GRIDS) if row["page"] == str(table.page)]
    bands = [read_json_column(row["column_headers_json"]) for row in rows]
    # Row 1 sits under the first band, which names no role for column 0 and
    # names DESCRIPTION at column 3.
    assert bands[1][0] is None
    assert bands[1][3] == "DESCRIPTION"
    # Row 4 sits under the second, which names column 0 DOCUMENT NO. and moves
    # DESCRIPTION to column 7.
    assert bands[4][0] == "DOCUMENT NO."
    assert bands[4][3] is None
    assert bands[4][7] == "DESCRIPTION"
    assert bands[4][-1] == "AMOUNT ($)"


def test_a_second_header_band_inherits_the_first_across_a_body_row() -> None:
    """The band walk looks back past a body row, and this is the case a rewrite breaks.

    `organization_detail` is header, body, header, header, body...: the second
    band's own row states nothing at column 3, and the label there has to come
    from the *first* band, two rows up and across an intervening body row. A
    walk that reset its accumulation at every non-header row would lose it and
    every test but this one would still pass.
    """
    table = next(
        table for page in pages_for(BOTH_GRIDS) for table in page.tables if grid_kind(table) == "organization_detail"
    )
    bands = [
        read_json_column(row["column_headers_json"]) for row in rows_for(BOTH_GRIDS) if row["page"] == str(table.page)
    ]
    # Row 2 is itself a header row; the band governing it is the one above it.
    assert bands[2][3] == "DESCRIPTION"
    assert bands[2][0] is None
    # Row 3 (the START/END sub-band) is governed by row 2's band alone.
    assert bands[3][0] == "DOCUMENT NO."
    # And a body row under both keeps the nearer band's roles, not the first's.
    assert bands[4][0] == "DOCUMENT NO."


def test_the_printed_page_label_is_stated_on_every_table_page() -> None:
    """139 of 139 measured pages state one, and it is what the volume's contents index by."""
    labels = [row["printed_page"] for row in rows_for(SUMMARY_ONLY)]
    assert None not in labels
    assert sorted(set(labels)) == ["A-1", "A-2", "A-3", "A-4", "A-5", "A-6", "A-7"]
    detail = {row["printed_page"] for row in rows_for(BOTH_GRIDS) if row["grid_kind"] != "appropriation_summary"}
    assert detail == {"B-1243", "B-1244", "B-1245", "B-1246", "B-1247", "B-1248"}


def test_the_office_block_comes_from_the_page_and_is_null_on_a_continuation_page() -> None:
    """The print states the office on the first page of a block only; the rest are NULL."""
    by_page = {}
    for row in rows_for(BOTH_GRIDS):
        by_page.setdefault(row["printed_page"], row)
    assert by_page["B-1243"]["office"] == "SENATOR JIM JUSTICE"
    assert by_page["B-1243"]["funding_year"] == "2025"
    assert by_page["B-1243"]["appropriation_title"] == ("SENATORS’ OFFICIAL PERSONNEL AND OFFICE EXPENSE ACCOUNT")
    assert by_page["B-1243"]["section_heading"] == "DETAILED AND SUMMARY STATEMENT OF EXPENDITURES"
    assert by_page["B-1244"]["office"] is None
    assert by_page["B-1244"]["section_heading"] is None
    # The summary section names an appropriation, never an office.
    assert by_page["A-1"]["office"] is None
    assert by_page["A-1"]["section_heading"] == "SUMMARY OF TRANSACTIONS BY APPROPRIATIONS"


def test_the_period_is_read_off_the_prints_own_column_headers() -> None:
    periods = {
        (row["grid_kind"], row["period_start"], row["period_end"]) for fixture in MEASURED for row in rows_for(fixture)
    }
    assert ("appropriation_summary", "2024-10-01", "2025-03-31") in periods
    assert ("appropriation_summary", "2025-10-01", "2026-03-31") in periods
    assert ("organization_detail", "2025-10-01", "2026-03-31") in periods
    # A payee_detail table's header states no date at all, and nothing invents one.
    assert ("payee_detail", None, None) in periods


def test_the_account_columns_are_filled_only_where_the_print_rules_the_cells() -> None:
    filled = [row for fixture in MEASURED for row in rows_for(fixture) if row["account_title"] is not None]
    assert {row["grid_kind"] for row in filled} == {"appropriation_summary"}
    assert all(row["cells_ruled"] == "true" for row in filled)
    first = next(row for row in rows_for(SUMMARY_ONLY) if row["row_kind"] == "entry")
    assert first["account_title"] == "COMPENSATION OF\nMEMBERS\n2023\n2024\n2025"
    assert first["account_number"] == "0100"


# ---------------------------------------------------------------------------
# The check that can fail.
# ---------------------------------------------------------------------------


#: What each fixture's section states on its own Totals row, read off the print
#: by eye so the check compares against something this code did not compute.
STATED_TOTALS = {
    SUMMARY_ONLY: {2: "1771557289.86", 6: "-649330011.60", 7: "1944352.28", 8: "1124171630.54"},
    BOTH_GRIDS: {2: "2055856462.50", 6: "-627015388.75", 7: "1693153.22", 8: "1430534226.97"},
}


@pytest.mark.parametrize("fixture", sorted(MEASURED))
def test_the_parsed_amounts_sum_to_the_prints_own_totals_row(fixture: str) -> None:
    """Seven money columns, 93 stacked amounts over 28 account rows, to the cent.

    This is the one check this family offers that can fail: a dropped cell, a
    column read one place over, or an amount parsed loosely all move a sum, and
    none of them would look like an error anywhere else.
    """
    checks = summary_totals(rows_for(fixture))
    assert len(checks) == 7
    for check in checks:
        assert check.agrees, f"column {check.column} ({check.header}): {check.stated} != {check.summed}"
    by_column = {check.column: check for check in checks}
    for column, stated in STATED_TOTALS[fixture].items():
        assert by_column[column].stated == Decimal(stated)
        assert by_column[column].summed == Decimal(stated)


def test_the_totals_check_notices_a_dropped_row() -> None:
    """The check above passes trivially if it cannot fail; prove it bites."""
    rows = list(rows_for(SUMMARY_ONLY))
    dropped = next(
        index
        for index, row in enumerate(rows)
        if row["grid_kind"] == "appropriation_summary" and row["row_kind"] == "entry" and row["amount_count"] != "0"
    )
    del rows[dropped]
    assert any(not check.agrees for check in summary_totals(rows))


def test_the_totals_check_refuses_rather_than_agreeing_with_nothing() -> None:
    """No stated total is not agreement, and must not read as one."""
    without = [row for row in rows_for(SUMMARY_ONLY) if row["row_kind"] != "total"]
    assert summary_totals(without) == []
    assert summary_totals([]) == []


# ---------------------------------------------------------------------------
# The helpers, directly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("1,234.56", Decimal("1234.56")),
        ("$19.96", Decimal("19.96")),
        (".00", Decimal("0.00")),
        ("-12,161,280.90", Decimal("-12161280.90")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("0.00", Decimal(0)),
        # The sign before the dollar sign: how the print writes every negative
        # in an organization summary, 72 distinct of them on the measured
        # pages. Stripping `$` first stranded the `-` and refused the amount.
        ("-$204,348.74", Decimal("-204348.74")),
        ("-$8,819.25", Decimal("-8819.25")),
        ("$-8,819.25", Decimal("-8819.25")),
    ],
)
def test_every_amount_spelling_the_print_uses_parses(printed: str, expected: Decimal) -> None:
    assert parse_amount(printed) == expected


@pytest.mark.parametrize(
    "printed",
    ["", "   ", "-", "—", "Totals", "2025", None, "X (REVOLVING)", "B-1243", "--5.00", "-$-5.00", "$"],
)
def test_a_string_the_print_does_not_mean_as_an_amount_refuses(printed: str | None) -> None:
    """A bare year, a dash and a label are not amounts; guessing would publish an invention.

    A doubled sign refuses too: the sign comes off exactly once, so `--5.00`
    is not quietly read as a negative five.
    """
    assert parse_amount(printed) is None


def test_a_bare_year_inside_an_account_title_is_not_counted_as_an_amount() -> None:
    """The title cell stacks 2023/2024/2025 under the account name; none is money."""
    row = next(row for row in rows_for(SUMMARY_ONLY) if row["account_number"] == "0100")
    amounts = read_json_column(row["amounts_json"])
    assert amounts[0] is None
    assert [one["amount"] for one in amounts[2]] == ["798584.35", "687246.58", "24949150.00"]
    # Seven money columns, three fiscal years stacked in each: 21, and not the
    # 25 a rule accepting bare integers would give -- it read the three years
    # in the title cell *and* the `0100` in the account-number cell as money.
    assert row["amount_count"] == "21"


def test_the_page_context_reads_nothing_out_of_an_empty_page() -> None:
    empty = page_context("")
    assert empty.printed_page is None and empty.office is None
    assert empty.funding_year is None and empty.funding_year_end is None
    assert empty.text_sha256 == digest("")


#: Printed page B-48 of `GPO-CDOC-119sdoc3-1.pdf` (PDF page 66), verbatim from
#: the retained dump. A two-year appropriation, which is the spelling that
#: broke the first funding-year rule.
B48_PAGE_TAIL = (
    "AMOUNT ($)\n"
    "START\n"
    "END\n"
    "DETAILED AND SUMMARY STATEMENT OF EXPENDITURES\n"
    "CHAPLAIN\n"
    "Funding Year          2021-2023\n"
    "SALARIES, OFFICERS AND EMPLOYEES\n"
    "B-48"
)


def test_a_multi_year_funding_block_states_its_office_like_any_other() -> None:
    """The regression the fixtures cannot reach, because both end before page 66.

    Five of the 83 office pages in the measured range spell a span --
    `Funding Year 2021-2023`, the Chaplain's blocks at printed B-48, B-49,
    B-51, B-53 and B-55. A rule matching only `\\d{4}` read no office on any of
    them, and because `office` is documented as forward-filled by the consumer,
    those rows would have been attributed to the *preceding* office: a wrong
    answer wearing a missing one's clothes.
    """
    context = page_context(B48_PAGE_TAIL)

    assert context.office == "CHAPLAIN"
    assert context.funding_year == "2021"
    assert context.funding_year_end == "2023"
    assert context.appropriation_title == "SALARIES, OFFICERS AND EMPLOYEES"
    assert context.section_heading == "DETAILED AND SUMMARY STATEMENT OF EXPENDITURES"
    assert context.printed_page == "B-48"


def test_a_single_year_funding_block_states_no_span() -> None:
    """`funding_year_end` is NULL for one year, so a span is told apart rather than folded."""
    single = B48_PAGE_TAIL.replace("2021-2023", "2023").replace("B-48", "B-50")
    context = page_context(single)

    assert context.office == "CHAPLAIN"
    assert context.funding_year == "2023"
    assert context.funding_year_end is None
    assert context.printed_page == "B-50"


@pytest.mark.parametrize(
    ("last_line", "expected"),
    [
        ("A-7", "A-7"),
        ("B-1243", "B-1243"),
        ("B-2-146", "B-2-146"),
        ("x", "x"),
        ("(iii)", "(iii)"),
        ("viii", "viii"),
        # Not page labels: an ordinary word of roman letters, a bare number,
        # and the cover's own last line. Each must land as NULL rather than be
        # published as a locator.
        ("civil", None),
        ("mix", None),
        ("2025", None),
        ("MAY 14, 2025—Ordered to lie on the table", None),
        ("$8,301,439.18", None),
    ],
)
def test_only_a_page_label_the_print_uses_is_read_as_one(last_line: str, expected: str | None) -> None:
    assert page_context(f"SOMETHING\n{last_line}").printed_page == expected


def test_the_table_period_refuses_a_spelling_the_print_does_not_use() -> None:
    class _Table:
        cells = (("FUNDS AVAILABLE AS OF the first of October",), ("UNEXPENDED BALANCE AS OF 2025-03-31",))

    assert table_period(_Table()) == (None, None)


def test_a_table_observation_missing_a_field_refuses_rather_than_shaping_a_row() -> None:
    from spicy_docs.schemas.tables import TableContractError

    class _NotATable:
        page = 1

    with pytest.raises(TableContractError, match="must state bbox"):
        shape_senate_expenditure_rows(
            _NotATable(),
            "",
            package_id="GPO-CDOC-119sdoc3",
            file_name="GPO-CDOC-119sdoc3-1.pdf",
            table_ordinal=0,
            page_count=1,
            pages_read=1,
            body_rendition="pdf",
            body_derivation="pdf-extraction-lines",
        )


def test_every_row_states_the_read_was_capped_and_names_the_rule_version() -> None:
    """These pages come out of a 1,335-page print, so every count over them is a floor."""
    rows = rows_for(SUMMARY_ONLY)
    assert {row["pages_capped"] for row in rows} == {"true"}
    assert {row["page_count"] for row in rows} == {"1335"}
    assert {row["pages_read"] for row in rows} == {"7"}
    assert {row["extraction_rule_version"] for row in rows} == {SENATE_EXPENDITURE_RULE_VERSION}


def test_one_package_publishes_two_files_of_the_same_pages() -> None:
    """Why ``file_name`` is in the identity: the package id alone would collide them.

    ``GPO-CDOC-119sdoc3.pdf`` (the Full Report) and ``GPO-CDOC-119sdoc3-1.pdf``
    (Part I) are two files of one package whose first sixty pages extract to
    byte-identical text, measured on the rollup's own retained extracts.
    """
    contract = TABLE_CONTRACTS["senate_expenditures"]
    assert "file_name" in contract.identity
    row = dict(rows_for(SUMMARY_ONLY)[0])
    twin = dict(row, file_name="GPO-CDOC-119sdoc3.pdf")
    assert contract.key(row) != contract.key(twin)
