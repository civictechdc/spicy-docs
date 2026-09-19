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

The printed tally is the original's, with one widening: it reports **every**
bill type present in the input, where the TS harness hard-coded ``HR`` and
``S`` and so silently omitted every joint and concurrent resolution it had
measured. Per bill type it reports how many extracted bill
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
from collections.abc import Callable, Iterable, Iterator, Sequence
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


def report(rows: Sequence[AuditRow], write: Callable[[str], object] = print) -> None:
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


def _candidate_rows(handle, reader: csv.DictReader, head_bytes: int) -> Iterator[dict[str, str]]:
    with handle:
        for row in reader:
            kept = {key: (value or "") for key, value in row.items() if key}
            kept["text"] = kept.get("text", "")[:head_bytes]
            yield kept


def read_candidates(path: Path, *, head_bytes: int = HEAD_BYTES) -> Iterator[dict[str, str]]:
    """Check the header now, stream the rows later, truncating each ``text`` on read.

    The original's SQL truncated with ``LEFT(bv.text, 8192)``; a CSV has no
    such projection, so the cut happens here, once per row, rather than after
    the whole file has been materialized. The header check stays eager so a
    misnamed column is refused when the file is opened, not part-way through
    a long run.
    """
    handle = path.open(newline="", encoding="utf-8")
    reader = csv.DictReader(handle)
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or ())]
    if missing:
        handle.close()
        raise SystemExit(f"{path}: missing required column(s): {', '.join(missing)}")
    return _candidate_rows(handle, reader, head_bytes)


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

    rows = audit(read_candidates(args.input, head_bytes=args.head_bytes), head_bytes=args.head_bytes)
    report(rows)
    if args.output is not None:
        write_rows(rows, args.output)
        print(f"CSV written to: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
