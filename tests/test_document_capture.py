"""The DocumentCapture v1 profiles and the six worked conversions, checked from what is committed.

Nothing here fetches: every capture is re-validated against the vendored
parent and its profile, its text stream is re-derived from the retained
artifact with another parser, and its rulespec fragments are re-validated.
The one PDF-derived input is the retained evidence document, never the PDF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis import document_capture as dc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "research" / "document-capture-schema-2026-09-19"
PINS = json.loads(dc.SCHEMAS.joinpath("PINS.json").read_text())
CAPTURES = sorted(OUTPUT.glob("*.capture.json"))


@pytest.fixture(scope="module")
def validators():
    return dc.validators()


def test_vendored_schemas_match_their_pins() -> None:
    assert dc.schema_pin(dc.PARENT_SCHEMA) == PINS["parent"]
    assert dc.schema_pin("rulespec/source-fragment.schema.json") == PINS["sourceFragment"]
    for name, pin in PINS["profiles"].items():
        assert dc.schema_pin(f"profiles/{name}.schema.json") == pin, name


@pytest.mark.parametrize("name", sorted(PINS["profiles"]))
def test_profile_composes_the_parent_without_redefining_it(name: str) -> None:
    profile = dc.load_schema(f"profiles/{name}.schema.json")
    assert dc.check_profile_composition(profile, dc.load_schema(dc.PARENT_SCHEMA)) == []
    assert profile["allOf"][1]["properties"]["profile"]["properties"]["name"]["const"] == name


def test_every_family_has_a_worked_conversion() -> None:
    families = {json.loads(p.read_text())["profile"]["name"] for p in CAPTURES}
    assert families == set(PINS["profiles"])


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_capture_validates_and_holds_its_invariants(path: Path, validators) -> None:
    parent, profiles, _ = validators
    capture = json.loads(path.read_text())
    assert capture["schema"] == PINS["parent"]
    assert capture["profile"]["schema"] == PINS["profiles"][capture["profile"]["name"]]
    assert [e.message for e in parent.iter_errors(capture)] == []
    assert [e.message for e in profiles[capture["profile"]["name"]].iter_errors(capture)] == []
    assert dc.check_invariants(capture) == []


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_text_stream_round_trips_from_the_retained_artifact(path: Path) -> None:
    capture = json.loads(path.read_text())
    artifact = (ROOT / capture["artifact"]["locator"]["path"]).read_bytes()
    assert dc.sha256(artifact) == capture["artifact"]["sha256"]
    evidence = json.loads(artifact) if capture["rendition"]["kind"] == "evidence-lines" else None
    independent, _ = dc.independent_text(capture["rendition"]["kind"], artifact, evidence)
    assert dc.sha256(independent) == capture["rendition"]["textStream"]["sha256"]
    assert "".join(s["exact"] for s in capture["evidence"]) == independent


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_leaf_fragments_are_valid_source_fragments(path: Path, validators) -> None:
    _, _, fragment_validator = validators
    capture = json.loads(path.read_text())
    fragments = json.loads(path.with_name(path.name.replace(".capture.json", ".fragments.json")).read_text())
    nodes = {n["id"]: n for n in capture["nodes"]}
    assert len(fragments) == 2
    assert dc.validate_fragments(fragments, fragment_validator) == []
    stream = "".join(s["exact"] for s in capture["evidence"])
    for entry in fragments:
        text = nodes[entry["node"]]["text"]
        for key in ("streamFragment", "renditionFragment"):
            quote = next(s for s in entry[key]["oa:hasSelector"] if s["@type"] == "oa:TextQuoteSelector")
            assert quote["oa:exact"] == text
            assert entry[key]["rkaf:fragmentContentDigest"] == "sha256:" + dc.sha256(text)
        positions = [s for s in entry["streamFragment"]["oa:hasSelector"] if s["@type"] == "oa:TextPositionSelector"]
        assert "".join(stream[s["oa:start"] : s["oa:end"]] for s in positions) == text
        if entry["carrierLocalFragmentUrn"]:
            assert entry["carrierLocalFragmentUrn"].endswith(
                f":{positions[0]['oa:start']}:{positions[0]['oa:end']}:sha256-{dc.sha256(text)}"
            )


def test_family_kinds_stay_inside_their_profile_namespace() -> None:
    for path in CAPTURES:
        capture = json.loads(path.read_text())
        for node in capture["nodes"]:
            prefix, _, _ = node["kind"].partition(":")
            assert node["kind"] in dc.CORE_KINDS or prefix == capture["profile"]["name"], (path.name, node["kind"])
