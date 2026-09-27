"""Retained XML fragments projected without inventing edition or target identity."""

import hashlib
import json
from pathlib import Path

from spicy_docs.schemas.native_reference_rows import (
    shape_ecfr_note,
    shape_uscode_reference,
    shape_uscode_source_credit,
)
from spicy_docs.sources.cfr.authority import scan_ecfr_authority_notes
from spicy_docs.sources.uscode.references import scan_uscode_references

FIXTURES = Path(__file__).parent / "fixtures"


def test_native_uscode_occurrences_and_source_credit_keep_fragment_uncertainty() -> None:
    path = FIXTURES / "uscode/title-05-s423.xml"
    body = path.read_bytes()
    refs, credits = [], []
    scan = scan_uscode_references(body, on_reference=refs.append, on_source_credit=credits.append)
    assert (scan.references, scan.source_credits) == (30, 1)
    context = {
        "source_record_key": "/us/usc/t5/s423",
        "input_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "source_locator": "retained:title-05-s423.xml",
    }
    rows = [shape_uscode_reference(r, occurrence_index=i, **context) for i, r in enumerate(refs)]
    assert len(rows) == 30
    assert all(r["edition"] is None for r in rows)
    assert "/us/usc/t5/s401" in {r["href"] for r in rows}
    assert len({r["source_path"] for r in rows}) == 30
    for raw, row in zip(refs, rows, strict=True):
        assert json.loads(row["attributes_json"]) == raw.element.attributes
        assert len(json.loads(row["ancestors_json"])) == len(raw.ancestors)
    credit = shape_uscode_source_credit(credits[0], occurrence_index=0, **context)
    assert "117–286" in credit["text"] and "136 Stat. 4255" in credit["text"]
    assert credit["observation_kind"] == "source_credit"


def test_ecfr_authority_and_source_notes_keep_distinct_roles_and_complete_text() -> None:
    body = (FIXTURES / "cfr/ecfr-authority-title1-part18.xml").read_bytes()
    auth, source = [], []
    scan = scan_ecfr_authority_notes(body, on_authority=auth.append, on_source=source.append)
    context = {
        "source_record_key": "retained:part18-fragment",
        "input_sha256": "sha256:" + scan.input_sha256,
        "source_locator": "retained:ecfr-authority-title1-part18.xml",
    }
    a = shape_ecfr_note(auth[0], occurrence_index=0, **context)
    s = shape_ecfr_note(source[0], occurrence_index=0, **context)
    assert (a["observation_kind"], s["observation_kind"]) == ("authority", "source_note")
    assert a["cfr_title"] is a["edition"] is None  # the filename is not source metadata
    assert a["cfr_part"] == "18"
    assert "44 U.S.C. 1506" in a["text"] and "E.O. 10530" in a["text"]
    assert "37 FR 23609" in s["text"]
    assert a["text"] == "".join(json.loads(a["text_runs_json"]))
    assert a["source_path"] != s["source_path"]


def test_unknown_empty_and_absent_hrefs_are_preserved() -> None:
    # Synthetic controls, not newly qualified publisher shapes.
    body = b'<section><ref href="opaque:unknown#fragment"/><ref href=""/><ref/></section>'
    refs = []
    scan_uscode_references(body, on_reference=refs.append)
    rows = [
        shape_uscode_reference(
            r,
            source_record_key="synthetic",
            input_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
            source_locator="synthetic:test",
            occurrence_index=i,
        )
        for i, r in enumerate(refs)
    ]
    assert [r["href"] for r in rows] == ["opaque:unknown#fragment", "", None]
