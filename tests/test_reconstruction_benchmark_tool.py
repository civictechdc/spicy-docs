"""The CFR benchmark renders its report from the saved sidecar, and reads a granule the way the publisher spells it.

The rendering test is the one that matters for the committed measurement: the
generated block in `docs/research/reconstruction-benchmark-2026-09-19.md` must
be reproducible from
`docs/research/reconstruction-benchmark-2026-09-19.json` alone, with no
network and no fetched body, or the numbers in the document and the numbers in
the pin can drift apart without anyone noticing.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spicy_docs.reconstruction.parse import parse_cfr
from spicy_docs.reconstruction.serialize import serialize_cfr
from tools.analysis.reconstruction_benchmark import (
    EDITIONS,
    MARK_END,
    MARK_START,
    SPLITS,
    TARGET_SECTIONS,
    Granule,
    _digest,
    _section_number,
    read_reference,
    render_block,
    rescore,
    score,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs" / "research" / "reconstruction-benchmark-2026-09-19.json"
REPORT = ROOT / "docs" / "research" / "reconstruction-benchmark-2026-09-19.md"
CFR_XML = ROOT / "tests" / "fixtures" / "cfr" / "annual-title30-vol3-sec716-2.xml"
FIXTURES = ROOT / "tests" / "fixtures" / "reconstruction" / "cfr"


def test_a_section_granule_id_yields_the_section_number_the_publisher_prints() -> None:
    package = "CFR-2025-title30-vol3"
    assert _section_number(f"{package}-sec716-2", package) == "716.2"
    assert _section_number(f"{package}-sec716-2-3", package) == "716.2-3"
    # Only section granules are paired; a chapter or part node is not one.
    assert _section_number(f"{package}-chapVII", package) is None
    assert _section_number(f"{package}-part716", package) is None


def test_a_granule_derives_both_renditions_and_its_split_from_the_publisher_s_coordinates() -> None:
    granule = Granule(2025, 30, 3, "CFR-2025-title30-vol3-sec716-2", "716.2")
    assert granule.package == "CFR-2025-title30-vol3"
    assert granule.pdf_url.endswith("/pdf/CFR-2025-title30-vol3-sec716-2.pdf")
    assert granule.xml_url.endswith("/xml/CFR-2025-title30-vol3-sec716-2.xml")
    assert granule.split == SPLITS[2025]


def test_every_edition_is_in_exactly_one_split_so_no_volume_reaches_two() -> None:
    years = [year for year, _title, _volume in EDITIONS]
    assert len(years) == len(set(years)), "one volume per edition, so the split is the volume"
    assert all(year in SPLITS for year in years)
    assert set(SPLITS.values()) == {"development", "tuning", "blind"}


def test_the_reference_reader_takes_the_section_subtree_and_its_paragraph_markers() -> None:
    reference = read_reference(CFR_XML.read_bytes())
    assert reference.section == "716.2"
    assert reference.elements[:2] == ("SECTNO", "SUBJECT") and reference.elements[-1] == "CITA"
    assert reference.markers[:4] == ("(a)", "(b)", "(c)", "(d)")
    assert "Steep-slope mining." in reference.text
    # FDSYS is publisher metadata about the granule, not the section's text.
    assert "Mineral Resources" not in reference.text


def test_the_fixture_section_scores_against_the_published_xml_of_the_same_section() -> None:
    """The one end-to-end case: the fixture PDF's evidence and the fixture XML are one document."""
    from spicy_docs.reconstruction.evidence import EvidenceDocument

    evidence = EvidenceDocument.from_json(
        json.loads((FIXTURES / "CFR-2025-title30-vol3-sec716-2.evidence.json").read_text())
    )
    granule = Granule(2025, 30, 3, "CFR-2025-title30-vol3-sec716-2", "716.2")
    document = parse_cfr(evidence)
    row = score(
        granule, document, serialize_cfr(document, section="716.2"), read_reference(CFR_XML.read_bytes()), schema=False
    )
    assert row["precision"] == 1.0 and row["recall"] == 1.0
    assert row["hierarchyF1"] == 1.0 and row["criticalDiscrepancies"] == 0
    # The boundary: this PDF's page range carries three neighbouring sections,
    # whose blocks are out of scope rather than lost.
    assert len(row["sectionsInRendition"]) > 1 and row["outOfScopeBlocks"] > 0
    assert row["blocks"] == evidence.to_json()["blocks"].__len__()


def test_rescore_refuses_a_body_whose_digest_moved() -> None:
    """A re-score cannot quietly measure different bytes than the numbers it replaces.

    Only the refusal is exercised: the agreeing-digest path would need a real
    PDF to reconstruct, and the fixture set holds evidence documents, not PDFs.
    """
    granule = Granule(2025, 30, 3, "CFR-2025-title30-vol3-sec716-2", "716.2")
    with tempfile.TemporaryDirectory() as name:
        scratch = Path(name)
        (scratch / f"{granule.granule_id}.pdf").write_bytes(b"%PDF-1.4 recorded bytes")
        (scratch / f"{granule.granule_id}.xml").write_bytes(b"<CFRGRANULE/>")
        row = {
            "granuleId": granule.granule_id,
            "package": granule.package,
            "year": granule.year,
            "title": granule.title,
            "volume": granule.volume,
            "section": granule.section,
            "split": granule.split,
            "pdfUrl": granule.pdf_url,
            "xmlUrl": granule.xml_url,
            "pdfSha256": _digest(b"%PDF-1.4 different bytes"),
            "xmlSha256": _digest(b"<CFRGRANULE/>"),
        }
        rows, manifest = rescore({"documents": [row]}, scratch, schema=False)
        assert rows[0]["error"] == "DigestMoved"
        assert "pdfSha256" in rows[0]["message"]
        assert manifest == [], "a body whose digest moved is not scored"
        # And a missing body is reported the same way rather than skipped.
        (scratch / f"{granule.granule_id}.pdf").unlink()
        rows, _ = rescore({"documents": [row]}, scratch, schema=False)
        assert rows[0]["error"] == "MissingBody"


def test_summarize_counts_a_failed_row_rather_than_dropping_it() -> None:
    rows = [
        {"granuleId": "a", "split": "blind", "error": "BenchmarkError"},
        {
            "granuleId": "b",
            "split": "blind",
            "precision": 1.0,
            "recall": 1.0,
            "hierarchyF1": 1.0,
            "referencePairs": 2,
            "criticalDiscrepancies": 0,
            "unresolvedRegions": 0,
            "outOfScopeBlocks": 3,
            "blocks": 10,
            "accepted": True,
            "findings": [{"check": "coverage", "passed": True}],
        },
    ]
    summary = summarize(rows)
    assert summary["documents"] == 2 and summary["scored"] == 1 and summary["failed"] == 1
    assert summary["failures"][0]["granuleId"] == "a"
    assert summary["blind"]["documents"] == 1 and summary["blind"]["coverageComplete"] == 1
    # A row with no timing must not become a zero in the mean.
    assert summary["blind"]["reconstructSeconds"] is None


@pytest.mark.skipif(not SIDECAR.exists(), reason="no saved measurement")
def test_the_report_block_renders_from_the_saved_sidecar_and_matches_what_is_committed() -> None:
    measures = json.loads(SIDECAR.read_text())
    block = render_block(measures)
    assert block.startswith(MARK_START) and block.endswith(MARK_END)
    committed = REPORT.read_text()
    start, end = committed.find(MARK_START), committed.find(MARK_END) + len(MARK_END)
    assert committed[start:end] == block, "run --offline to bring the document back in line with its sidecar"


@pytest.mark.skipif(not SIDECAR.exists(), reason="no saved measurement")
def test_the_saved_measurement_states_its_pins_its_corpus_and_its_request_count() -> None:
    measures = json.loads(SIDECAR.read_text())
    assert measures["profile"] == "cfr/1"
    assert len(measures["guideSha256"]) == 64 and len(measures["schemaSha256"]) == 64
    assert measures["targetSections"] == TARGET_SECTIONS
    assert measures["requests"]["total"] <= 120, "the run is bounded and the bound is recorded"
    assert {entry["split"] for entry in measures["editions"]} == {"development", "tuning", "blind"}
    scored = [row for row in measures["documents"] if "precision" in row]
    assert scored, "the committed sidecar holds a real run"
    for row in scored:
        # Every scored body is pinned by digest, so a rerun can prove it read
        # the same bytes without this repository carrying them.
        assert len(row["pdfSha256"]) == 64 and len(row["xmlSha256"]) == 64
        assert row["pdfUrl"].startswith("https://www.govinfo.gov/content/pkg/")
    assert len({row["granuleId"] for row in measures["documents"]}) == len(measures["documents"])
