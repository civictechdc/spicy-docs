"""Positive native multi-RIN evidence and unchanged scalar compatibility."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from spicy_docs.interpretation.communication_rin import (
    RIN_LABEL,
    RinFinding,
    rin_from_report_nature,
    rin_occurrences_from_report_nature,
)
from spicy_docs.interpretation.identifier_shapes import PUBLISHED_RIN
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


#: Report natures from the fork's ``house_communications`` (read 2026-09-27; receipt
#: ``fork-execution-2026-09-21/spicy-docs-0501/rin-agreement/``), each cut to the RIN clause, then the scalar's RIN and
#: the listed RINs. The en-dash row and the last three are constructed: the review of 0.50.1 found the three inputs on
#: which 0.50.0's own scalar pattern read a RIN the list does not.
AGREEMENT = [
    ("(RIN: 2125-AF80; 2130-AD05; 2132-AB51)", "2125-AF80", ["2125-AF80", "2130-AD05", "2132-AB51"]),  # 119-EC-4554
    ("(RIN: 3084-AB60) (RIN: 3084-AB72) (RIN: 3084-AB74)", "3084-AB60", ["3084-AB60", "3084-AB72", "3084-AB74"]),
    ("AD 2025-11-01] (RIN: 2120-Aa64) received June 9, 2025.", "2120-AA64", ["2120-AA64"]),  # 119-EC-1209
    ("[CMS-1849-F and CMS-0062-F] (RINs: 0938-AV79 and 0938-AV44) received", None, ["0938-AV79", "0938-AV44"]),
    ("Major final rule - Regulation Identification Number 0910-AJ05 Medical Devices", None, ["0910-AJ05"]),
    ("AD 2026-01-08] (IRN: 2120-AA64) received January 29, 2026.", None, ["2120-AA64"]),  # 119-EC-2773
    ("see 1004-AF39 and (RIN: 1004-AF40)", "1004-AF40", ["1004-AF39", "1004-AF40"]),
    ("[Docket No.: 241212-0326] (RIN: 0648-XE368) received", None, []),  # 119-EC-1226
    ("A rule (RIN 2060\u2013AV12).", "2060-AV12", ["2060-AV12"]),
    ("A damaged RIN (RIN: 1625-AAOO) and a placeholder (RIN 2060-XXXX).", None, []),
    ("(RIN2060-AV12)", None, []),
    ("(RIN: 2060-AV12\u2013A)", None, []),
    ("(RIN: 2060-AV12/2060-AV13)", None, []),
]


@pytest.mark.parametrize(("nature", "scalar", "listed"), AGREEMENT, ids=lambda value: str(value)[:24])
def test_the_scalar_is_the_first_listed_rin_the_label_directly_precedes(nature, scalar, listed):
    """The list needs no label; the scalar is the first listed occurrence a ``RIN`` label directly precedes.

    So the list holds every scalar RIN at the scalar's span, by construction; every listed RIN is a published key, so a
    longer token, a damaged RIN or one the shared reader does not separate is in neither.
    """
    finding = rin_from_report_nature(nature)
    occurrences = rin_occurrences_from_report_nature(nature)
    assert finding.rin == scalar
    assert [occurrence.rin for occurrence in occurrences] == listed
    for occurrence in occurrences:
        assert re.fullmatch(PUBLISHED_RIN, occurrence.rin)
        assert nature[occurrence.span_start : occurrence.span_end] == occurrence.matched_text
    labelled = [o for o in occurrences if RIN_LABEL.search(nature, 0, o.span_start)]
    if scalar is None:
        assert finding == RinFinding(None, "unmatched", None)
        assert not labelled
    else:
        first = labelled[0]
        assert finding.rin == first.rin
        assert finding.matched_text.startswith("RIN") and finding.matched_text.endswith(first.matched_text)
        assert nature[first.span_end - len(finding.matched_text) : first.span_end] == finding.matched_text


def test_a_host_passes_the_list_it_read_and_gets_the_same_scalar():
    """``occurrences=`` reuses the list a host already read, and the answer is the one the field alone gives."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/record_communications/house-119-ec-1278-report-nature.json").read_text()
    )
    natures = [nature for nature, _, _ in AGREEMENT] + [fixture["reportNature"], "", None]
    for nature in natures:
        occurrences = rin_occurrences_from_report_nature(nature)
        assert rin_from_report_nature(nature, occurrences=occurrences) == rin_from_report_nature(nature)
    other = rin_occurrences_from_report_nature("(RIN: 1004-AF40)")
    with pytest.raises(ValueError, match="another report nature"):
        rin_from_report_nature("(RIN: 1004-AF39)", occurrences=other)
    with pytest.raises(ValueError, match="another report nature"):
        rin_from_report_nature(None, occurrences=other)
    with pytest.raises(TypeError):
        rin_from_report_nature(3133, occurrences=())  # type: ignore[arg-type]
