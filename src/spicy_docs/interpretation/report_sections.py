"""Two aggregates over parsed report sections, ported from BillTrax's SQL as pure Python.

BillTrax computed both with a MySQL query joining ``bills``, ``committee_reports``
and ``report_sections`` (``committee-reports.ts``). There is no database here:
each function takes the equivalent joined rows as plain mappings and does the
filter/sort/dedupe MySQL did, in the same order, over whatever iterable of rows
the caller's own storage layer supplies.

Both BillTrax functions took their filter values as parameters alongside an
implicit ``WHERE`` clause baked into the SQL; a pure function over rows needs
those same filter values explicitly, since there is no query to embed them in.
``getAgencyRecurrence(agencyLabel, currentBillId)``'s second parameter was
already dead code -- named ``_currentBillId``, never read in its body
(``committee-reports.ts:136-138``) -- so it is dropped here rather than ported.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypedDict


class ReportSectionRow(TypedDict):
    """One joined row across ``bills``, ``committee_reports`` and ``report_sections``.

    Field names follow BillTrax's own SQL aliases: `congress`/`bill_number` come
    from `bills`; `bill_id`, `report_id`, `chamber`, `report_label`, `date`,
    `report_text`, `source` come from `committee_reports`; `section_id`, `seq`,
    `agency_label`, `body` come from `report_sections`. Neither function below
    reads every field on every row -- `agency_recurrence` only needs `congress`,
    `bill_number`, `report_label`, `agency_label`, `body`; `sections_for_agency`
    needs the rest -- but one row shape serves both aggregates, matching how
    BillTrax's own two queries both joined the same three tables.
    """

    congress: int
    bill_number: str
    bill_id: str
    report_id: str
    chamber: str
    report_label: str
    date: str | None
    report_text: str
    source: str
    section_id: str
    seq: int
    agency_label: str
    body: str


def agency_recurrence(rows: Iterable[ReportSectionRow], agency_label: str, *, limit: int = 20) -> dict[str, Any]:
    """Port of ``getAgencyRecurrence`` (committee-reports.ts:136-176).

    How many distinct congresses have report language for ``agency_label``, across every bill in
    ``rows`` (not just one). Matches BillTrax's own normalization: both the query's ``agency_label``
    and each row's are compared ``upper().strip()``, not exact. A row whose ``agency_label`` is
    ``None`` never matches, the same way SQL's ``UPPER(TRIM(rs.agency_label)) = ?`` evaluates to
    unknown, not true, for a ``NULL`` column regardless of ``?``. Faithfully reproduces two more
    things the SQL does that a naive re-reading would not, kept because this ports the query
    BillTrax actually ran, not the query it meant to write:

    - ``SELECT DISTINCT ... LIMIT 20`` caps the matching **rows** (deduped on the four selected columns)
      before the per-congress dedup below runs, not the number of distinct congresses returned. If the
      top `limit` rows repeat a congress (e.g. a House and a Senate report for the same congress), the
      returned count can undercount true recurrence. Not measured against data with duplicate-congress
      collisions; carried over as BillTrax computed it, not corrected.
    - The SQL is ``ORDER BY b.congress DESC`` with no secondary key, so MySQL leaves ties within a
      congress unspecified. This port uses Python's stable sort, so tied rows keep the caller's input
      order -- a deterministic choice BillTrax's SQL never made, not a behavior being matched.
    """
    normalized = agency_label.upper().strip()
    matches = [
        row for row in rows if row["agency_label"] is not None and row["agency_label"].upper().strip() == normalized
    ]
    # SELECT DISTINCT on exactly the four projected columns, first occurrence wins.
    distinct = list(
        {(row["congress"], row["bill_number"], row["report_label"], row["body"]): row for row in matches}.values()
    )
    ordered = sorted(distinct, key=lambda row: row["congress"], reverse=True)[:limit]

    seen: set[int] = set()
    congresses: list[dict[str, Any]] = []
    for row in ordered:
        if row["congress"] in seen:
            continue
        seen.add(row["congress"])
        congresses.append(
            {
                "congress": row["congress"],
                "bill_number": row["bill_number"],
                "report_label": row["report_label"],
                "excerpt": row["body"][:200],
            }
        )
    return {"count": len(congresses), "congresses": congresses}


def sections_for_agency(
    rows: Iterable[ReportSectionRow], bill_id: str, agency_label: str
) -> tuple[dict[str, Any], ...]:
    """Port of ``getSectionsForAgency`` (committee-reports.ts:178-210).

    Every report section for one bill naming ``agency_label``, one ``{report, section}`` pair per
    matching section, ordered by chamber. Unlike ``agency_recurrence``, BillTrax matches ``agency_label`` here exactly -- case-sensitive,
    untrimmed (`rs.agency_label = ?`, no `UPPER`/`TRIM`). Kept as-is: BillTrax's two functions genuinely
    use different match rules, and harmonizing them here would stop this from being a port.

    ``ORDER BY cr.chamber`` alone (alphabetical: conference, house, senate); Python's stable sort keeps
    the caller's input order for rows sharing a chamber, matching how a single-key SQL sort leaves ties
    in whatever order the storage engine already held them.
    """
    matches = [row for row in rows if row["bill_id"] == bill_id and row["agency_label"] == agency_label]
    ordered = sorted(matches, key=lambda row: row["chamber"])
    return tuple(
        {
            "report": {
                "id": row["report_id"],
                "bill_id": row["bill_id"],
                "chamber": row["chamber"],
                "label": row["report_label"],
                "date": row["date"],
                "text": row["report_text"],
                "source": row["source"],
                "sections": [],
            },
            "section": {
                "id": row["section_id"],
                "report_id": row["report_id"],
                "seq": row["seq"],
                "agency_label": row["agency_label"],
                "body": row["body"],
            },
        }
        for row in ordered
    )
