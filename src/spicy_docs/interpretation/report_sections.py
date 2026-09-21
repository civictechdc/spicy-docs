"""Two aggregates over parsed report sections, ported from BillTrax's SQL as pure Python.

BillTrax computed both with a MySQL query joining ``bills``,
``committee_reports`` and ``report_sections``; with no database here, each
function takes the equivalent joined rows as plain mappings and does the same
filter/sort/dedupe MySQL did, in the same order, over whatever iterable of
rows the caller's own storage layer supplies. BillTrax's
``getAgencyRecurrence(agencyLabel, currentBillId)`` second parameter was
already dead code -- never read in its body -- so it is dropped here rather
than ported.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypedDict


class ReportSectionRow(TypedDict):
    """One joined row across ``bills``, ``committee_reports`` and ``report_sections``.

    Field names follow BillTrax's own SQL aliases: `congress`/`bill_number`
    come from `bills`; `bill_id`, `report_id`, `chamber`, `report_label`,
    `date`, `report_text`, `source` come from `committee_reports`; `section_id`,
    `seq`, `agency_label`, `body` come from `report_sections`. One row shape
    serves both aggregates, matching how both of BillTrax's queries joined the
    same three tables.
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

    How many distinct congresses have report language for ``agency_label``,
    across every bill in ``rows`` (not just one), compared ``upper().strip()``
    as the query did -- a row whose label is ``None`` never matches, the same
    way SQL's ``UPPER(TRIM(rs.agency_label)) = ?`` is unknown for a ``NULL``
    column. Two further things the SQL did are kept, because this ports the
    query BillTrax actually ran rather than the query it meant to write:
    ``SELECT DISTINCT ... LIMIT 20`` caps the matching **rows** (deduped on the
    four selected columns) before the per-congress dedup, so the returned count
    can undercount true recurrence; and the single-key ``ORDER BY b.congress
    DESC`` left ties unspecified, so this port's stable sort keeps the caller's
    input order -- a deterministic choice BillTrax's SQL never made.
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

    Every report section for one bill naming ``agency_label``, one ``{report,
    section}`` pair per matching section, ordered by chamber. Unlike
    :func:`agency_recurrence`, the label match here is exact -- case-sensitive
    and untrimmed (``rs.agency_label = ?``) -- kept as-is because BillTrax's two
    functions genuinely used different match rules, and the single-key
    ``ORDER BY cr.chamber`` leaves rows sharing a chamber in the caller's input
    order, as a single-key SQL sort leaves ties in storage order.
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
