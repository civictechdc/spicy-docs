"""The bill-identify acceptance harness reads a CSV and prints the tally the TS harness did."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.analysis.audit_bill_identify import audit, main, read_candidates, report, write_rows

CANDIDATES = [
    {
        "bill_type": "HR",
        "number": "7148",
        "congress": "119",
        "short_title": "Department of Defense Appropriations Act 2026",
        "sponsor": "Mr. COLE",
        "text": (
            "119th Congress, 1st Session\nH.R. 7148\nMr. COLE introduced the following bill\n\nA BILL\n\n"
            "This Act may be cited as the ''Department of Defense Appropriations Act, 2026''.\n"
            "SECTION 1. SHORT TITLE.\n"
        ),
    },
    {
        "bill_type": "S",
        "number": "998",
        "congress": "119",
        "short_title": "Energy Programs Act",
        "sponsor": "Ms. CANTWELL",
        "text": "S. 998\n\nAN ACT\n\nTo authorize programs of the Department of Energy\n\nSECTION 1.",
    },
    {"bill_type": "S", "number": "12", "congress": "119", "short_title": "Known Act", "sponsor": "", "text": "S. 12"},
]


def write_input(path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CANDIDATES[0]))
        writer.writeheader()
        writer.writerows(CANDIDATES)
    return path


def test_the_audit_reports_extraction_quality_per_bill_type() -> None:
    rows = audit(CANDIDATES)
    assert [row.bill_number_matches for row in rows] == [True, True, True]
    assert [row.title_source for row in rows] == ["may-be-cited-as", "fallback-marker", "none"]
    assert rows[0].title_jaccard == 1.0
    assert rows[0].sponsor_matches is True
    assert rows[0].section_headings == 1


def test_the_tally_names_each_type_its_sources_and_the_unexpected_failures() -> None:
    lines: list[str] = []
    report(audit(CANDIDATES), write=lines.append)
    text = "\n".join(lines)
    assert "HR  n=1  bill_number=1/1 (100%)  title_extracted=1/1  sponsor=1/1" in text
    assert "S  n=2  bill_number=2/2 (100%)  title_extracted=1/2  sponsor=0/2" in text
    assert "may-be-cited-as=1  avg_jaccard=1.00" in text
    assert "UNEXPECTED FAILURES" in text
    assert "S-12 (119)" in text


def test_a_clean_run_says_so_rather_than_printing_an_empty_list() -> None:
    lines: list[str] = []
    report(audit(CANDIDATES[:2]), write=lines.append)
    assert "No title_source=none failures" in "\n".join(lines)


def test_the_per_row_csv_round_trips(tmp_path: Path) -> None:
    write_rows(audit(CANDIDATES), tmp_path / "rows.csv")
    written = list(csv.DictReader((tmp_path / "rows.csv").open(encoding="utf-8")))
    assert [row["extracted_bill_number"] for row in written] == ["HR-7148", "S-998", "S-12"]


def test_a_missing_required_column_is_refused(tmp_path: Path) -> None:
    (tmp_path / "bad.csv").write_text("bill_type,number\nHR,1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing required column"):
        read_candidates(tmp_path / "bad.csv")


def test_the_entry_point_runs_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = write_input(tmp_path / "candidates.csv")
    assert main(["--input", str(source), "--output", str(tmp_path / "rows.csv")]) == 0
    assert "AUDIT SUMMARY" in capsys.readouterr().out
    assert (tmp_path / "rows.csv").exists()
