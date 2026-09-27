"""Positive native multi-RIN evidence and unchanged scalar compatibility."""

import hashlib
import json
from pathlib import Path

from spicy_docs.interpretation.communication_rin import rin_from_report_nature, rin_occurrences_from_report_nature
from tests.test_record_communications import numbered


def test_every_rin_in_retained_native_communication_field_has_its_span():
    fixture = Path(__file__).parent / "fixtures/record_communications/house-119-ec-1278-report-nature.json"
    record = json.loads(fixture.read_text())
    text = record["reportNature"]
    occurrences = rin_occurrences_from_report_nature(text)
    assert [f.rin for f in occurrences] == record["expected_rins"]
    assert [f.ordinal for f in occurrences] == [0, 1]
    assert rin_from_report_nature(text).rin == "3235-AK79"
    for finding in occurrences:
        assert text[finding.span_start : finding.span_end] == finding.matched_text == finding.rin
        assert finding.field_sha256 == hashlib.sha256(text.encode()).hexdigest()
        assert finding.rule_version == "004"


def test_retained_authority_subject_and_referral_remain_independent_fields():
    from spicy_docs.interpretation.citations import find_citations

    entries = numbered("CREC-2016-02-12-pt1-PgH815-4")
    entry = entries[4329]
    assert [r.rin for r in rin_occurrences_from_report_nature(entry.report_nature)] == ["1218-AC97"]
    assert "OSHA-2015-0003" in entry.report_nature
    laws = find_citations(entry.legal_authority, kinds=("public_law", "usc_section"))
    assert {"104-public-121", "5-801"} <= {f.target_key for f in laws}
    assert entry.committee_names
    assert not entries[4340].split_resolved
    assert "General Counsel, Peace Corps" in entries[4340].from_clause


def test_missing_empty_and_repeated_occurrences_do_not_change_compatibility():
    assert rin_occurrences_from_report_nature(None) == rin_occurrences_from_report_nature("") == ()
    text = "RIN: 3235-AK79; RIN: 3235-AK79"  # constructed repetition control, not another native specimen
    rows = rin_occurrences_from_report_nature(text)
    assert len(rows) == 2 and rows[0].span_start != rows[1].span_start
    assert rin_from_report_nature(text).rin == rows[0].rin


def test_native_multi_rin_shaper_roundtrip():
    from dataclasses import asdict

    from spicy_docs.schemas.congress_index_tables import shape_house_communication

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/record_communications/house-119-ec-1278-report-nature.json").read_text()
    )
    detail = {
        "congress": fixture["congress"],
        "number": fixture["number"],
        "communicationType": {"code": "EC"},
        "reportNature": fixture["reportNature"],
    }
    values = [asdict(item) for item in rin_occurrences_from_report_nature(detail["reportNature"])]
    row = shape_house_communication(detail, detail, rin_occurrences=values)
    assert json.loads(row["rin_occurrences_json"]) == values
    assert shape_house_communication(detail, None)["rin_occurrences_json"] is None
    assert shape_house_communication(detail, detail, rin_occurrences=[])["rin_occurrences_json"] == "[]"
