"""The Report of the Secretary of the Senate's ruled tables, one row per ruled row.

Build-order item 4 of the
[revised order](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md):
the one PDF-only family whose value is a **table** and not a citation.  Its
citation yield against the package MODS is zero -- the single apparent survivor,
the bill key ``S08``, is a false positive -- while a full read of the eight
sampled volumes carries **65,261 distinct dollar figures over 161,536 rows**
against a publisher listing that states two fields.

**Acquisition for this family wires up when the package-id grammar lands.**
``sources/govinfo/bodies.py``'s grammar reaches neither ``BUDGET-*`` nor
``GPO-CDOC-*``, so ``GovInfoBodyAcquirer`` cannot fetch these packages in
product code yet; the register's B4 row carries that as a decision record.
This module is built over the bytes the rollup retained and takes no
acquisition seam of its own: the shapers are pure over one
``extraction.model.TableObservation`` and the page text beside it, so a caller
that reaches the package any way at all can fill the table.

## What the ruled tables actually are

Measured 2026-09-20 over 160 pages of two retained volumes
(`GPO-CDOC-119sdoc3-1.pdf` pages 1-80, `GPO-CDOC-119sdoc6-2.pdf` pages 1-80;
the note is ``docs/research/senate-expenditure-tables-2026-09-20.md``,
receipt ``~/Work/corpora/supply-2026-09-02/receipts/senate-expenditure-tables-2026-09-20/``).
**139 tables on 139 pages -- never two on one page, never one spanning two.**
The print draws three ruled grids and they are not interchangeable:

=========================  ======  =============================================
Grid                       Tables  What one ruled row is
=========================  ======  =============================================
``appropriation_summary``  13      One appropriation account, all nine cells
                                   ruled: the title with its fiscal years
                                   stacked, the account number, and six money
                                   columns each stacking one amount per year.
                                   The section's last row is the print's own
                                   ``Totals``.
``organization_detail``    83      One office's funding block.  Rows 0 and 2
                                   are two separate header bands; the body is
                                   **one** ruled cell holding the whole
                                   organization summary or the whole payee
                                   block.
``payee_detail``           43      A continuation page of the same block: the
                                   ``DOCUMENT NO. ... AMOUNT ($)`` header band
                                   and one blob cell under it.
=========================  ======  =============================================

**The decisive measurement is that the print does not rule the payee lines.**
Of 6,172 cells, 3,905 are positions PyMuPDF finds no cell region at all.  Every
one of the 58 ``appropriation_summary`` body rows has all nine cells ruled; every
``organization_detail`` and ``payee_detail`` body row has exactly **one** of ten
or one of seven.  A payee line --
``00646684 02/19/2025 PATTY MURRAY 02/19/2025 02/19/2025 SENATOR TRANSPORTATION $19.96``
-- is a *line inside one cell*, not a ruled row.

So this contract does **not** carry ``payee_name``, ``document_number``,
``date_posted`` or a singular ``amount`` column, although the print's own header
band names all four.  Filling them would mean splitting a blob cell on a guess,
which is the failure the rollup already made four times before the sample
corrected it, and a column NULL on every row of every fixture is the defect the
[design brief](../../../docs/research/table-contracts-2026-09-19.md) names for
``hearing_transcripts``.  What lands instead is the blob **whole** in
``cells_json``, the roles the print's header states for each column in
``column_headers_json``, and ``cells_ruled`` so a consumer's ``WHERE
cells_ruled`` is exactly the rows whose cells are separate facts.  Splitting the
payee block is a text rule for ``interpretation/``, and it is unmeasured.

## Where each value comes from

Nothing here is assumed from position.  A column's role is the label the
print's own header band states at that index, and the band is the nearest one
above this row -- which matters because ``organization_detail`` has two, and the
role at column 0 changes from the office block to ``DOCUMENT NO.`` partway down
one table.

The office, the funding year and the appropriation title come from the **page
text**, not from the table: measured, the page states them on 83 of 139 table
pages and the table's own first cell on only 21, and every one of those 21 is
also in the page text.  On the other 56 -- continuation pages -- the print
states no office, so the column is NULL and a consumer forward-fills by
``printed_page``.  ``printed_page`` itself is the last non-empty line of the
page text and was present on **139 of 139** table pages (``A-7``, ``B-1243``):
it is the locator the volume's own table of contents indexes by, and the PDF
page number is not.

## Two rows, as the print states them

One ``appropriation_summary`` entry row, from page A-1 of ``GPO-CDOC-119sdoc3``,
file ``GPO-CDOC-119sdoc3-1.pdf``, rendition ``pdf``, derivation
``pdf-extraction-lines``.  Nine ruled cells; the title cell stacks the fiscal
years and every money cell stacks one amount per year, in the same order::

    COMPENSATION OF MEMBERS / 2023 2024 2025   0100   798,584.35 687,246.58 24,949,150.00   ...

Its column headers come from the two-row band above it: ``APPROPRIATION TITLE``,
``NO.``, ``FUNDS AVAILABLE AS OF October 1, 2024``, the three
``FUNDING ADJUSTMENTS`` sub-columns, ``NET EXPENDITURES``,
``REVOLVING FUND RECEIPTS`` and ``UNEXPENDED BALANCE AS OF March 31, 2025`` --
the last two of which give ``period_start`` ``2024-10-01`` and ``period_end``
``2025-03-31``.  Account numbers measured on these pages run ``0100`` for the
annual accounts through ``4046`` and up for the revolving funds.

One ``organization_detail`` page, B-1243: the page states
``SENATOR TIM KAINE``-style office lines -- here
``SENATOR JIM JUSTICE``, ``Funding Year 2025``,
``SENATORS’ OFFICIAL PERSONNEL AND OFFICE EXPENSE ACCOUNT`` -- and its
second header band names ``DOCUMENT NO.``, ``DATE POSTED``, ``PAYEE NAME``,
``START``, ``END``, ``DESCRIPTION`` and ``AMOUNT ($)``.  Under that band the
print rules **one** cell, so ``cells_ruled`` is ``false`` and
``WHERE cells_ruled`` excludes the whole page; on the summary row above it is
``true``.  A ``payee_detail`` continuation page states no date in any header,
so its period is NULL rather than borrowed from the volume's cover, and no
office, so ``office`` is NULL and a consumer forward-fills.

## Counts published here are floors

Every count is bounded by ``pages_read``, and these volumes run 1,264 to 3,018
pages.  ``pages_capped`` says so per row rather than leaving a partial read to
look like a whole one.  The amounts are published as decimal strings and never
as a canonical key: the ``dollar_amount`` canonical the rollup used erases the
decimal separator and was measured colliding, so a dollar figure is not a join
key until that is fixed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from spicy_docs.schemas.tables import (
    Row,
    TableContractError,
    digest,
    flag,
    json_column,
    table_contract,
    text,
)

#: This module's own rule version, the column a merge prefers the larger value
#: of.  Zero-padded decimal because the column is compared as a string, the
#: same spelling ``document_citations.rule_version`` uses.
SENATE_EXPENDITURE_RULE_VERSION = "001"

#: Every header label the print states, whitespace collapsed, exactly as
#: measured.  A cell is a header label when it equals one of these or ends one
#: of :data:`_DATED_HEADERS` -- nothing is inferred from a column's position.
HEADER_LABELS: frozenset[str] = frozenset(
    {
        "APPROPRIATION TITLE",
        "NO.",
        "FUNDING ADJUSTMENTS",
        "SUPPLEMENTALS",
        "TRANSFERS",
        "RESCISSIONS/ WITHDRAWALS",
        "NET EXPENDITURES",
        "REVOLVING FUND RECEIPTS",
        "DOCUMENT NO.",
        "DATE POSTED",
        "PAYEE NAME",
        "OBLIGATION/SERVICE DATES",
        "START",
        "END",
        "DESCRIPTION",
        "AMOUNT ($)",
        "TOTAL FUNDING YTD ($)",
    }
)

#: The header labels that carry a date, matched by prefix because the date is
#: the volume's reporting period and changes every printing.
_DATED_HEADERS: tuple[str, ...] = (
    "FUNDS AVAILABLE AS OF",
    "NET FUNDS AVAILABLE AS OF",
    "UNEXPENDED BALANCE AS OF",
    "NET EXPENDITURES FOR THE PERIOD OF",
)

#: The two section headings the print states above a ruled grid.
SECTION_HEADINGS: tuple[str, ...] = (
    "SUMMARY OF TRANSACTIONS BY APPROPRIATIONS",
    "DETAILED AND SUMMARY STATEMENT OF EXPENDITURES",
)

#: Which grid a table is, decided by the label its own first row states.
_GRID_BY_FIRST_LABEL: tuple[tuple[str, str], ...] = (
    ("APPROPRIATION TITLE", "appropriation_summary"),
    ("DOCUMENT NO.", "payee_detail"),
    ("TOTAL FUNDING YTD ($)", "organization_detail"),
)

_FUNDING_YEAR = re.compile(r"^Funding Year\s+(\d{4})$")
_SLASHED = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_LONG_DATE = re.compile(r"\b([A-Z][a-z]+) (\d{1,2}), (\d{4})\b")
_PERIOD = re.compile(r"PERIOD OF\s+(\d{2}/\d{2}/\d{4})\s+THRU\s+(\d{2}/\d{2}/\d{4})")
#: The print's own page label: ``A-7``, ``B-1243``, ``B-2-146``, ``x``, ``(iii)``.
_PRINTED_PAGE = re.compile(r"[A-Z]-[\d-]+|\(?[ivxlc]+\)?|\d+")
#: The print's own total labels.  ``Totals`` is the appropriation-summary grid's
#: last row; ``ORGANIZATION TOTALS`` is inside the organization block's one cell.
_TOTALS_CELL = "Totals"
_ORGANIZATION_TOTALS = "ORGANIZATION TOTALS"

_MONTHS = {
    "January": "01",
    "February": "02",
    "March": "03",
    "April": "04",
    "May": "05",
    "June": "06",
    "July": "07",
    "August": "08",
    "September": "09",
    "October": "10",
    "November": "11",
    "December": "12",
}

SENATE_EXPENDITURES = table_contract(
    "senate_expenditures",
    grain=(
        "One row per ruled row of one ruled table on one page of a Report of the Secretary of the Senate, with "
        "the cells exactly as the print states them and the roles its own header band names."
    ),
    identity=("package_id", "file_name", "page", "table_ordinal", "row_ordinal", "text_sha256"),
    version_column="extraction_rule_version",
    columns={
        "package_id": (
            "The GovInfo package id the page belongs to, `GPO-CDOC-119sdoc3`.  Not unique on its own: one "
            "package publishes the whole report and each of its parts as separate PDFs, so `file_name` is in "
            "the identity beside it."
        ),
        "file_name": (
            "Which PDF of that package this page is in, `GPO-CDOC-119sdoc3-1.pdf`.  Part of the identity "
            "because the package's `Full Report` and `Part I` files carry the same printed pages -- measured "
            "byte-identical extracted text over the first 60 pages of GPO-CDOC-119sdoc3 -- and keying on the "
            "package alone would collide them."
        ),
        "page": "The one-based PDF page the table was found on, as the extraction states it.",
        "table_ordinal": (
            "Which table on that page, zero-based, in the order the extraction returned them.  Measured 139 of "
            "139 pages carry exactly one, so this is `0` throughout the sample and exists because nothing in "
            "the print guarantees it."
        ),
        "row_ordinal": "Which ruled row of that table, zero-based, top to bottom.",
        "text_sha256": (
            "Digest of the page text this row's context was read from, and part of the identity.  A page, "
            "table and row ordinal mean nothing without it: a re-extraction that finds one more ruled band "
            "moves every ordinal after it, and keying on the digest is what stops two extractions of one page "
            "from colliding on one identity and silently merging.  It pins the text, not the table finder, so "
            "a change in the table finder alone is not visible here."
        ),
        "printed_page": (
            "The print's own page label, the last non-empty line of the page text: `A-7`, `B-1243`, `x`.  "
            "Present on 139 of 139 measured table pages.  This is the locator the volume's table of contents "
            "indexes by; the PDF page number is not."
        ),
        "section_heading": (
            "The section heading the page states, one of `SUMMARY OF TRANSACTIONS BY APPROPRIATIONS` or "
            "`DETAILED AND SUMMARY STATEMENT OF EXPENDITURES`.  NULL on a continuation page, which repeats "
            "neither."
        ),
        "grid_kind": (
            "Which of the print's three ruled grids this table is, decided by the label its own first row "
            "states: `appropriation_summary`, `organization_detail` or `payee_detail`.  NULL where the first "
            "row states none of the three, so an unrecognised grid is visible rather than mislabelled."
        ),
        "row_kind": (
            "What the print makes this row: `header` where at least two of its cells are header labels, "
            "`total` where it is the grid's own `Totals` row or carries `ORGANIZATION TOTALS`, `entry` "
            "otherwise."
        ),
        "cells_ruled": (
            "Whether the print rules this row into more than one cell.  `true` on every "
            "`appropriation_summary` body row (nine cells of nine) and `false` on every "
            "`organization_detail` and `payee_detail` entry row (one of ten, one of seven), so "
            "`WHERE cells_ruled` selects exactly the rows whose cells are separate facts rather than one "
            "block of text."
        ),
        "office": (
            "The office or account the page names above its `Funding Year` line, `SENATOR TIM KAINE`.  NULL "
            "on a continuation page, which the print leaves unlabelled; a consumer forward-fills in "
            "`printed_page` order."
        ),
        "funding_year": "The four-digit funding year the page's own `Funding Year` line states; NULL where it states none.",
        "appropriation_title": (
            "The appropriation the page names under its funding year, joined to one line; the module "
            "docstring quotes one in full.  NULL where the page states none."
        ),
        "period_start": (
            "The first day of the period the table's own column headers state, as ISO `2024-10-01`.  Read "
            "from `FUNDS AVAILABLE AS OF October 1, 2024` or from the first date of a `PERIOD OF` header, the "
            "only two spellings measured; NULL where no header states one, which is every `payee_detail` "
            "table."
        ),
        "period_end": (
            "The last day of that period, as ISO `2025-03-31`, from `UNEXPENDED BALANCE AS OF March 31, 2025` "
            "or from the same header's second date.  NULL on the same terms as `period_start`."
        ),
        "column_headers_json": (
            "One entry per column: the header label governing this row at that index, whitespace collapsed "
            "and exactly as the print spells it, or null where the band names none.  The band is the nearest "
            "run of header rows above this one, which is what makes the role correct in an "
            "`organization_detail` table -- it carries two bands, and column 0 goes from the office block to "
            "`DOCUMENT NO.` partway down."
        ),
        "cells_json": (
            "One entry per column: the cell exactly as the print states it, newlines and all, or null where "
            "the extraction found no cell region there.  This is the row; every other content column is a "
            "promotion out of it and none replaces it."
        ),
        "account_title": (
            "The cell whose governing header is `APPROPRIATION TITLE`, which carries the account name with "
            "its fiscal years stacked under it, or `Totals` on the section's own total row.  Filled only "
            "where `cells_ruled`, so it is never a blob cell read as a title."
        ),
        "account_number": (
            "The cell whose governing header is `NO.`, the Senate's four-digit appropriation account number "
            "(`0100`, `4046`).  Filled on the same terms as `account_title`; the print states it empty on the "
            "`Totals` row."
        ),
        "amounts_json": (
            "One entry per column: null where the cell states no amount, otherwise every line of that cell "
            "that parses, in printed order, as objects carrying the exact printed line and its decimal.  A "
            "money cell stacks one amount per fiscal year, which is why this is a list and not a scalar, and "
            "a line that does not parse is not here and stands unchanged in `cells_json`."
        ),
        "amount_count": "How many amounts this row states across every column; `0` where it states none.",
        "table_row_count": "How many ruled rows the table this row belongs to has.",
        "table_column_count": (
            "How many ruled columns it has.  Measured 7, 9 and 10 across the sample, one value per grid kind."
        ),
        "bbox_x0": "Left edge of the table's bounding box, in normalized displayed-page coordinates from a top-left origin.",
        "bbox_y0": "Top edge of that box, on the same scale.",
        "bbox_x1": "Right edge of that box, on the same scale.",
        "bbox_y1": "Bottom edge of that box, on the same scale.",
        "page_count": "How many pages the whole PDF has, as the extraction states it: 1,335 and 1,264 on the two measured volumes.",
        "pages_read": "How many pages the extraction actually read, which a bounded read makes smaller than `page_count`.",
        "pages_capped": (
            "Whether the read stopped short of the document, so every count taken over these rows is a floor."
        ),
        "body_rendition": "Which rendition the cells were read from; `pdf` for this family, which offers no other.",
        "body_derivation": (
            "How that rendition became cells and text, as the caller states it: `pdf-extraction-lines` for the "
            "`NativeText` read these rows were measured on."
        ),
        "extraction_rule_version": (
            "This module's rule version, so a re-extraction under a corrected rule is attributable; the merge "
            "prefers the larger value.  Zero-padded decimal, because the column is compared as a string."
        ),
    },
)


#: An amount as this print spells it: an optional sign, an optional ``$``,
#: grouped digits, and a decimal point that is **required**.
_AMOUNT = re.compile(r"-?\d*\.\d+")


def parse_amount(value: str | None) -> Decimal | None:
    """The print's own amount spelling as a decimal, or ``None`` where it is not one.

    Measured spellings: ``1,234.56``, ``$19.96``, ``.00``, a negative as either
    ``-12,161,280.90`` or the accounting ``(1,234.56)``.

    **The decimal point is required, and that is a measurement rather than a
    convention.**  Over 160 pages of two volumes, 1,316 printed lines are
    amount-shaped and every one carries a ``.dd`` tail; the 143 that do not are
    32 distinct strings and all of them are appropriation account numbers
    (``0100`` to ``4326``) or fiscal years (``2023`` to ``2026``), which the
    print stacks inside the account-title and account-number cells.  Accepting a
    bare integer read those years as money -- caught by
    ``tests/test_senate_expenditures.py``, and invisible to the totals check,
    which never reaches column 0.
    """
    if value is None:
        return None
    body = value.strip()
    if not body:
        return None
    negative = body.startswith("(") and body.endswith(")")
    if negative:
        body = body[1:-1].strip()
    body = body.lstrip("$").strip().replace(",", "")
    if _AMOUNT.fullmatch(body) is None:
        return None
    try:
        parsed = Decimal(body)
    except InvalidOperation:  # pragma: no cover - the pattern above already refuses these
        return None
    return -parsed if negative else parsed


def _collapse(cell: str | None) -> str | None:
    return None if cell is None else " ".join(cell.split())


def _is_header_label(collapsed: str | None) -> bool:
    if not collapsed:
        return False
    return collapsed in HEADER_LABELS or collapsed.startswith(_DATED_HEADERS)


def _iso(value: str) -> str | None:
    """``10/01/2024`` or ``October 1, 2024`` as ISO, or ``None`` for any other spelling."""
    slashed = _SLASHED.search(value)
    if slashed is not None:
        month, day, year = slashed.groups()
        return f"{year}-{month}-{day}"
    long = _LONG_DATE.search(value)
    if long is not None:
        name, day, year = long.groups()
        month = _MONTHS.get(name)
        if month is not None:
            return f"{year}-{month}-{int(day):02d}"
    return None


@dataclass(frozen=True, slots=True)
class PageContext:
    """What every row of one page repeats, read off the page text exactly once.

    Taken per page rather than per row: a page with eleven ruled rows would
    otherwise scan and hash the same text eleven times, which is
    ``O(rows * characters)`` for facts that do not change between rows.
    """

    printed_page: str | None
    section_heading: str | None
    office: str | None
    funding_year: str | None
    appropriation_title: str | None
    text_sha256: str | None


def page_context(page_text: str) -> PageContext:
    """One page's printed locator and office block, from the page text alone.

    The print states the office, the funding year and the appropriation title
    as a block ending just before the page label, and states them on the first
    page of an office block only.  The rule is the block the print draws: find
    its ``Funding Year`` line, take the line above as the office and the lines
    below up to the page label as the title.
    """
    lines = [line.strip() for line in page_text.split("\n") if line.strip()]
    if not lines:
        return PageContext(None, None, None, None, None, digest(page_text))
    last = lines[-1]
    printed_page = last if _PRINTED_PAGE.fullmatch(last) else None
    heading = next((line for line in lines if line in SECTION_HEADINGS), None)
    office = year = title = None
    for index, line in enumerate(lines):
        found = _FUNDING_YEAR.fullmatch(line)
        if found is None:
            continue
        year = found.group(1)
        office = lines[index - 1] if index else None
        tail = lines[index + 1 : -1] if printed_page is not None else lines[index + 1 :]
        title = " ".join(tail) or None
        break
    return PageContext(printed_page, heading, office, year, title, digest(page_text))


def _governing_headers(cells: Sequence[Sequence[str | None]], row_ordinal: int) -> list[str | None]:
    """The header labels governing one row, from the nearest band of header rows above it.

    A band is a run of consecutive header rows; the governing one is the run
    ending at the last header row before ``row_ordinal``.  Reading only that run
    is what keeps an ``organization_detail`` table's two bands apart: its first
    band names column 3 ``DESCRIPTION`` for the organization summary and its
    second names column 7 ``DESCRIPTION`` for the payee lines, and a row under
    the second must not inherit the first.
    """
    width = len(cells[0]) if cells else 0
    header_rows = [i for i in range(row_ordinal) if _is_header_row(cells[i])]
    if not header_rows:
        return [None] * width
    band: list[int] = [header_rows[-1]]
    for index in reversed(header_rows[:-1]):
        if index != band[0] - 1:
            break
        band.insert(0, index)
    labels: list[str | None] = [None] * width
    # Nearest band row wins at a column both state: the sub-band under
    # FUNDING ADJUSTMENTS names SUPPLEMENTALS, TRANSFERS and RESCISSIONS,
    # and those are the roles, not the span above them.
    for index in band:
        for column, cell in enumerate(cells[index]):
            collapsed = _collapse(cell)
            if _is_header_label(collapsed):
                labels[column] = collapsed
    return labels


def _is_header_row(row: Sequence[str | None]) -> bool:
    """Two header labels make a header row; one does not.

    One is not enough because a body cell can hold a word the header vocabulary
    also uses -- the blob cells carry ``DESCRIPTION`` and ``END`` inside
    sentences -- while no measured body row states two of them as whole cells.
    """
    return sum(1 for cell in row if _is_header_label(_collapse(cell))) >= 2


def grid_kind(table: object) -> str | None:
    """Which of the print's three grids a table is, from the label its first row states."""
    cells = table.cells
    first = {_collapse(cell) for cell in cells[0]}
    for label, kind in _GRID_BY_FIRST_LABEL:
        if label in first:
            return kind
    return None


def table_period(table: object) -> tuple[str | None, str | None]:
    """The reporting period the table's own column headers state, as ISO dates.

    Read from the headers and never from the volume's cover: a continuation
    page states no cover, and a ``payee_detail`` table states no date at all,
    which is why both are NULL there rather than filled from somewhere else.
    """
    start = end = None
    for row in table.cells:
        for cell in row:
            collapsed = _collapse(cell)
            if not collapsed:
                continue
            period = _PERIOD.search(collapsed)
            if period is not None:
                start = start or _iso(period.group(1))
                end = end or _iso(period.group(2))
            elif collapsed.startswith(("FUNDS AVAILABLE AS OF", "NET FUNDS AVAILABLE AS OF")):
                start = start or _iso(collapsed)
            elif collapsed.startswith("UNEXPENDED BALANCE AS OF"):
                end = end or _iso(collapsed)
    return start, end


def _row_kind(row: Sequence[str | None]) -> str:
    if _is_header_row(row):
        return "header"
    stated = [cell for cell in row if cell is not None]
    if stated and _collapse(stated[0]) == _TOTALS_CELL:
        return "total"
    if any(_ORGANIZATION_TOTALS in (cell or "") for cell in row):
        return "total"
    return "entry"


def _row_amounts(row: Sequence[str | None]) -> tuple[list[list[dict[str, str]] | None], int]:
    """Every amount the row states, per column, in printed order.

    A money cell stacks one amount per fiscal year, so the unit is the line and
    not the cell.  A line that does not parse contributes nothing and stands
    unchanged in ``cells_json``.
    """
    columns: list[list[dict[str, str]] | None] = []
    total = 0
    for cell in row:
        if cell is None:
            columns.append(None)
            continue
        found = [
            {"text": line.strip(), "amount": str(amount)}
            for line in cell.split("\n")
            if (amount := parse_amount(line)) is not None
        ]
        total += len(found)
        columns.append(found or None)
    return columns, total


def shape_senate_expenditure_rows(
    table: object,
    page_text: str,
    *,
    package_id: str,
    file_name: str,
    table_ordinal: int,
    page_count: int,
    pages_read: int,
    body_rendition: str,
    body_derivation: str,
    context: PageContext | None = None,
) -> list[Row]:
    """Every published row of one ruled table, pure over the observation and the page text.

    ``table`` is an ``extraction.model.TableObservation``, read structurally --
    ``page``, ``bbox``, ``row_count``, ``column_count`` and ``cells`` -- so this
    module stays the stdlib-only leaf ``schemas`` is and takes no import from
    ``extraction``.  ``context`` is :func:`page_context`'s output, passed in when
    a caller shapes several tables from one page so the text is scanned and
    hashed once; it is computed here when a caller shapes one table alone.

    For a table of ``R`` rows and ``C`` columns over a page of ``N`` characters
    this is ``O(N + R * C)`` with one pass per cell, and the page scan is paid
    once per page rather than once per row.
    """
    for attribute in ("page", "bbox", "row_count", "column_count", "cells"):
        if not hasattr(table, attribute):
            raise TableContractError(f"a table observation must state {attribute}")
    if context is None:
        context = page_context(page_text)
    cells = table.cells
    kind = grid_kind(table)
    period_start, period_end = table_period(table)
    capped = pages_read < page_count
    bbox = table.bbox
    rows: list[Row] = []
    for ordinal, row in enumerate(cells):
        headers = _governing_headers(cells, ordinal)
        ruled = sum(1 for cell in row if cell is not None) > 1
        amounts, amount_count = _row_amounts(row)
        promoted = {
            "account_title": None,
            "account_number": None,
        }
        if ruled:
            for column, label in enumerate(headers):
                if label == "APPROPRIATION TITLE":
                    promoted["account_title"] = row[column]
                elif label == "NO.":
                    promoted["account_number"] = row[column]
        rows.append(
            {
                "package_id": text(package_id),
                "file_name": text(file_name),
                "page": text(table.page),
                "table_ordinal": text(table_ordinal),
                "row_ordinal": text(ordinal),
                "text_sha256": text(context.text_sha256),
                "printed_page": text(context.printed_page),
                "section_heading": text(context.section_heading),
                "grid_kind": text(kind),
                "row_kind": text(_row_kind(row)),
                "cells_ruled": flag(ruled),
                "office": text(context.office),
                "funding_year": text(context.funding_year),
                "appropriation_title": text(context.appropriation_title),
                "period_start": text(period_start),
                "period_end": text(period_end),
                "column_headers_json": json_column(headers),
                "cells_json": json_column(list(row)),
                "account_title": text(promoted["account_title"]),
                "account_number": text(promoted["account_number"]),
                "amounts_json": json_column(amounts),
                "amount_count": text(amount_count),
                "table_row_count": text(table.row_count),
                "table_column_count": text(table.column_count),
                "bbox_x0": text(bbox.x0),
                "bbox_y0": text(bbox.y0),
                "bbox_x1": text(bbox.x1),
                "bbox_y1": text(bbox.y1),
                "page_count": text(page_count),
                "pages_read": text(pages_read),
                "pages_capped": flag(capped),
                "body_rendition": text(body_rendition),
                "body_derivation": text(body_derivation),
                "extraction_rule_version": text(SENATE_EXPENDITURE_RULE_VERSION),
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class ColumnTotal:
    """One column of the print's own ``Totals`` row against the rows it totals."""

    column: int
    header: str | None
    stated: Decimal
    summed: Decimal

    @property
    def agrees(self) -> bool:
        return self.stated == self.summed


def summary_totals(rows: Sequence[Row]) -> list[ColumnTotal]:
    """The print's stated ``Totals`` row against the entries above it, column by column.

    A check that can fail, and the only one this family offers: the
    ``appropriation_summary`` section ends with a row the print labels
    ``Totals``, and each of its money columns is the sum of every amount in that
    column over every entry row of the section -- across pages, because the
    section runs seven of them.  Summing every *line* of every cell is what the
    print itself does, since a cell stacks one amount per fiscal year.

    Refuses to answer rather than answering weakly: no ``total`` row, or more
    than one, returns an empty list, so a caller cannot read "nothing to check"
    as agreement.  ``rows`` must be the shaped rows of one whole section; a
    partial section would disagree and should.
    """
    from spicy_docs.schemas.tables import read_json_column

    summary = [row for row in rows if row["grid_kind"] == "appropriation_summary"]
    totals = [row for row in summary if row["row_kind"] == "total"]
    if len(totals) != 1:
        return []
    stated_row = totals[0]
    entries = [row for row in summary if row["row_kind"] == "entry"]
    stated_amounts = read_json_column(stated_row["amounts_json"])
    headers = read_json_column(stated_row["column_headers_json"])
    out: list[ColumnTotal] = []
    for column, found in enumerate(stated_amounts):
        if not found:
            continue
        stated = sum((Decimal(one["amount"]) for one in found), Decimal(0))
        summed = Decimal(0)
        for row in entries:
            cell = read_json_column(row["amounts_json"])[column]
            if cell:
                summed += sum((Decimal(one["amount"]) for one in cell), Decimal(0))
        out.append(ColumnTotal(column, headers[column], stated, summed))
    return out


__all__ = [
    "HEADER_LABELS",
    "SECTION_HEADINGS",
    "SENATE_EXPENDITURES",
    "SENATE_EXPENDITURE_RULE_VERSION",
    "ColumnTotal",
    "PageContext",
    "grid_kind",
    "page_context",
    "parse_amount",
    "shape_senate_expenditure_rows",
    "summary_totals",
    "table_period",
]
