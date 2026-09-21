"""Native report headings survive without becoming resolved agency identities."""

import hashlib
from pathlib import Path

from spicy_docs.extraction.body_text import rendition_text
from spicy_docs.schemas.committee_report_tables import REPORT_SECTIONS, shape_report_section
from spicy_docs.sources.agency_reports.report_blocks import parse_agency_blocks

FIXTURES = Path(__file__).parent / "fixtures"


def _rows(text, package):
    blocks = parse_agency_blocks(text)
    rows = [
        REPORT_SECTIONS.checked(shape_report_section(block, package_id=package, seq=seq))
        for seq, block in enumerate(blocks)
    ]
    assert "".join(text[start:end] for start, end in (block.char_span for block in blocks)) == text
    return rows


def test_native_report_headings_are_preserved_without_inventing_agencies():
    raw = (FIXTURES / "govinfo_bodies/body-CRPT-119hrpt796.htm").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "43eb74dac1580417ebb6f61bbc4b65b0c7eb0582d3057690fdd30140856ab971"
    text = rendition_text(raw, rendition="htm", media_type="text/html").text
    rows = _rows(text, "CRPT-119hrpt796")
    assert len(rows) == 8
    assert all(row["agency_label"] is None and row["agency_key"] is None for row in rows)
    assert [row["heading"] for row in rows] == [
        None,
        "HOUSE OF REPRESENTATIVES",
        "R E P O R T",
        "CONTENTS",
        "DECREASES (-) IN DIRECT SPENDING",
        "INCREASES IN SPENDING SUBJECT TO APPROPRIATION",
        "PART III--READJUSTMENT AND RELATED BENEFITS",
        "SUBCHAPTER II--EDUCATIONAL ASSISTANCE",
    ]
    assert "[To accompany H.R. 5634]" in rows[2]["body"]
    assert "Estimated Budget Authority" in rows[4]["body"]
    assert "Estimated Authorization" in rows[5]["body"]


def test_native_agency_heading_and_account_text_survive_without_an_identity_claim():
    # An actual publisher page, retained as a reduced single-page PDF. The
    # heading names an office, but no publisher agency identifier is present.
    raw = (FIXTURES / "gpo_pdf_tables/CRPT-113srpt77.page11.pdf").read_bytes()
    text = rendition_text(raw, rendition="pdf").text
    rows = _rows(text, "CRPT-113srpt77")
    office = next(row for row in rows if row["heading"] == "OFFICE OF THE SECRETARY AND EXECUTIVE MANAGEMENT")
    assert office["agency_label"] is None and office["agency_key"] is None
    assert "Immediate Office of the Secretary" in office["body"]
    assert "4,280" in office["body"]
    assert "Office of Policy" in office["body"]
    start, end = int(office["char_start"]), int(office["char_end"])
    assert office["heading"] in text[start:end]
    assert office["pattern"] == "office"


def test_unheaded_report_has_no_synthetic_heading_or_agency():
    (row,) = _rows("Unheaded report text.", "CRPT-119hrpt796")
    assert row["heading"] is None
    assert row["agency_label"] is None and row["agency_key"] is None
    assert row["body"] == "Unheaded report text."
    assert row["pattern"] == "full_report"
