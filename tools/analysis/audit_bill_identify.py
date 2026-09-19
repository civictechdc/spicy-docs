"""Measure how well bill-signal extraction reads real bill text, per bill type.

The acceptance harness that travelled with ``extractSignals``
(``BillTrax/scripts/audit-bill-identify.ts``), with its database query replaced
by a CSV the caller supplies, so the measurement runs offline against any
pinned sample. Run from the repository root:

  uv run --frozen python -m tools.analysis.audit_bill_identify \\
      --input <candidates.csv> --output <per-row.csv>

The input CSV needs one row per bill with the columns ``bill_type``,
``number``, ``congress``, ``short_title``, ``sponsor`` and ``text``; ``text``
is the version text, and the harness reads the first ``--head-bytes``
characters of it (8192 by default, as the original's ``LEFT(bv.text, 8192)``
did). Extra columns are ignored.

The printed tally is the original's: per bill type, how many extracted bill
numbers agree with the catalog, how many titles were extracted at all, how
many sponsors agree, and a breakdown by ``title_source`` with the mean token
Jaccard against the catalog's short title for each source. Then the list the
original called unexpected failures -- a bill whose ``title_source`` is
``none`` although the catalog holds a short title for it, which is the one
outcome that says extraction lost something it should have found.

What this cannot see: a title the catalog spells differently from the document
scores a low Jaccard without either side being wrong, and a bill with no
``short_title`` contributes to no Jaccard mean at all. The counts are about
extraction, not about the catalog being right.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from spicy_docs.interpretation.bill_signals import (
    TITLE_SOURCES,
    extract_signals,
    normalize_for_comparison,
    sponsor_last_name_of,
    token_jaccard,
)

HEAD_BYTES = 8192
REQUIRED_COLUMNS = ("bill_type", "number", "congress", "text")


@dataclass(frozen=True, slots=True)
class AuditRow:
    bill_type: str
    number: str
    congress: str
    short_title: str
    sponsor: str
    extracted_bill_number: str
    bill_number_matches: bool
    title_source: str
    extracted_title: str
    title_jaccard: float
    extracted_sponsor: str
    sponsor_matches: bool
    section_headings: int


def audit_row(row: dict[str, str], *, head_bytes: int) -> AuditRow:
    signals = extract_signals(row.get("text", "")[:head_bytes])
    bill_type = row.get("bill_type", "").strip()
    number = row.get("number", "").strip()
    short_title = row.get("short_title", "").strip()
    sponsor = row.get("sponsor", "").strip()

    extracted_ref = f"{signals.bill_type}-{signals.bill_number}" if signals.bill_type and signals.bill_number else ""
    jaccard = (
        token_jaccard(signals.normalized_title, normalize_for_comparison(short_title))
        if signals.normalized_title and short_title
        else 0.0
    )
    catalog_last_name = sponsor_last_name_of(sponsor) if sponsor else ""
    return AuditRow(
        bill_type=bill_type,
        number=number,
        congress=row.get("congress", "").strip(),
        short_title=short_title,
        sponsor=sponsor,
        extracted_bill_number=extracted_ref,
        bill_number_matches=signals.bill_type == bill_type and signals.bill_number == number,
        title_source=signals.title_source,
        extracted_title=signals.normalized_title or "",
        title_jaccard=round(jaccard, 2),
        extracted_sponsor=signals.sponsor_last_name or "",
        sponsor_matches=bool(
            signals.sponsor_last_name and catalog_last_name and signals.sponsor_last_name == catalog_last_name
        ),
        section_headings=len(signals.section_headings),
    )


def audit(rows: Iterable[dict[str, str]], *, head_bytes: int = HEAD_BYTES) -> tuple[AuditRow, ...]:
    return tuple(audit_row(row, head_bytes=head_bytes) for row in rows)


def _percent(part: int, whole: int) -> str:
    return "0" if whole == 0 else f"{part / whole * 100:.0f}"


def report(rows: Sequence[AuditRow], write=print) -> None:
    """Print the per-type tally and the unexpected-failure list."""
    write(f"\nLoaded {len(rows)} bill+version rows.\n")
    write("=== AUDIT SUMMARY ===\n")
    for bill_type in sorted(Counter(row.bill_type for row in rows)):
        subset = [row for row in rows if row.bill_type == bill_type]
        total = len(subset)
        numbers = sum(row.bill_number_matches for row in subset)
        titles = sum(bool(row.extracted_title) for row in subset)
        sponsors = sum(row.sponsor_matches for row in subset)
        write(
            f"{bill_type}  n={total}  bill_number={numbers}/{total} ({_percent(numbers, total)}%)  "
            f"title_extracted={titles}/{total}  sponsor={sponsors}/{total}"
        )
        for source in TITLE_SOURCES:
            in_source = [row for row in subset if row.title_source == source]
            if not in_source:
                continue
            comparable = [row for row in in_source if row.short_title]
            suffix = ""
            if comparable:
                suffix = f"  avg_jaccard={sum(row.title_jaccard for row in comparable) / len(comparable):.2f}"
            write(f"    {source}={len(in_source)}{suffix}")
        write("")

    failures = [row for row in rows if row.title_source == "none" and row.short_title]
    if failures:
        write("=== UNEXPECTED FAILURES (title_source=none with known short_title) ===")
        for row in failures:
            write(f"  - {row.bill_type}-{row.number} ({row.congress}) - short_title: {row.short_title!r}")
        write("")
    else:
        write("=== No title_source=none failures for bills with known short_title ===\n")


def write_rows(rows: Sequence[AuditRow], path: Path) -> None:
    fields = list(AuditRow.__slots__)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or ())]
        if missing:
            raise SystemExit(f"{path}: missing required column(s): {', '.join(missing)}")
        return [{key: (value or "") for key, value in row.items() if key} for row in reader]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="CSV of candidate bills and their version text")
    parser.add_argument("--output", type=Path, help="optional per-row CSV to write")
    parser.add_argument(
        "--head-bytes", type=int, default=HEAD_BYTES, help=f"characters read per row (default {HEAD_BYTES})"
    )
    args = parser.parse_args(argv)
    if args.head_bytes < 1:
        raise SystemExit("--head-bytes must be a positive integer")

    rows = audit(read_candidates(args.input), head_bytes=args.head_bytes)
    report(rows)
    if args.output is not None:
        write_rows(rows, args.output)
        print(f"CSV written to: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
