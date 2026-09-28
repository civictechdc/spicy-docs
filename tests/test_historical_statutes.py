"""Historical source rows remain distinct when their page/bill keys collide."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.sources.historical_statutes import (
    HistoricalStatutesError,
    parse_legisworks_volume,
    parse_nabors_table,
)

FIXTURES = Path(__file__).parent / "fixtures" / "historical_statutes"
LEGISWORKS = "9aeafcf279afdcc137dd9a6ef0d6688ef072a99d"
NABORS = "406661269dcf691cc123daf294f4b5bed87dba1c"


def test_retained_fixture_pins():
    for record in json.loads((FIXTURES / "provenance.json").read_text()):
        assert hashlib.sha256((FIXTURES / record["file"]).read_bytes()).hexdigest() == record["fixture_sha256"]


def test_legisworks_shared_pages_keep_each_law_and_pdf():
    raw = (FIXTURES / "legisworks-volume16-head.yaml").read_bytes()
    result = parse_legisworks_volume(raw, volume=16, commit=LEGISWORKS)
    assert result["input_sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert result["source_url"].endswith(f"/{LEGISWORKS}/data/016.yaml")
    records = result["records"]
    assert [r["fields"]["page"] for r in records] == [1, 1, 3, 3]
    assert [r["fields"]["number"] for r in records] == [1, 2, 3, 5]
    assert [r["source_record_index"] for r in records] == list(range(4))
    assert records[1]["pdf_url"].endswith("/16/STATUTE-16-Pg1a.pdf")
    assert records[0]["fields"]["title"] is None


def test_legisworks_keeps_fractional_numbers_and_unknown_fields():
    raw = b"- {volume: 36, page: 352, npages: 1, file: STATUTE-36-Pg352.pdf, number: '167\xc2\xbd', future: [a, b]}"
    row = parse_legisworks_volume(raw, volume=36, commit=LEGISWORKS)["records"][0]
    assert row["fields"]["number"] == "167½"
    assert row["fields"]["future"] == ["a", "b"]


def test_nabors_preserves_blank_context_and_shared_statute_page():
    raw = (FIXTURES / "nabors-head.csv").read_bytes()
    result = parse_nabors_table(raw, commit=NABORS)
    rows = result["records"]
    assert rows[0]["fields"]["congress"] == ""
    assert rows[0]["fields"]["date"] == "1789-06-01"
    assert rows[5]["fields"]["stat-page-end"] == ""
    assert rows[5]["fields"]["stat-page-start"] == rows[6]["fields"]["stat-page-start"] == "49"
    assert rows[5]["fields"]["bill-number"] != rows[6]["fields"]["bill-number"]
    assert [(r["line_start"], r["line_end"]) for r in rows] == [(n, n) for n in range(2, 10)]


@pytest.mark.parametrize("raw", [b"", b"a,b\n1,2\n", b"<html>Not found</html>"])
def test_nabors_refuses_non_table_success_shapes(raw):
    with pytest.raises(HistoricalStatutesError):
        parse_nabors_table(raw, commit=NABORS)


def test_nabors_preserves_wrong_width_and_source_error_rows():
    raw = (FIXTURES / "nabors-head.csv").read_bytes()
    rows = parse_nabors_table(raw + b"1,2\n89,21,99,41,4,0,403,5-20-30,HR,369,,ERROR\n", commit=NABORS)["records"]
    assert rows[-2]["fields"] is None
    assert rows[-2]["cells"] == ["1", "2"]
    assert rows[-2]["reason"] == "field_count"
    assert rows[-1]["fields"] is None
    assert rows[-1]["status"] == "unmapped"
    assert rows[-1]["reason"] == "source_error_marker"
    assert rows[-1]["cells"][-1] == "ERROR"


def test_nabors_refuses_exceeded_bounds():
    raw = (FIXTURES / "nabors-head.csv").read_bytes()
    for options in ({"max_rows": 1}, {"max_bytes": 10}, {"max_bytes": True}, {"max_rows": True}, {"commit": "main"}):
        with pytest.raises(HistoricalStatutesError):
            parse_nabors_table(raw, **({"commit": NABORS} | options))


def test_legisworks_refuses_wrong_volume_and_unsafe_locator():
    raw = (FIXTURES / "legisworks-volume16-head.yaml").read_bytes()
    with pytest.raises(HistoricalStatutesError, match="requested volume"):
        parse_legisworks_volume(raw, volume=1, commit=LEGISWORKS)
    with pytest.raises(HistoricalStatutesError, match="filename"):
        parse_legisworks_volume(raw.replace(b"STATUTE-16-Pg1.pdf", b"../../secret.pdf"), volume=16, commit=LEGISWORKS)
