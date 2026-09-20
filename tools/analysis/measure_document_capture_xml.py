"""Measure full capture XML reversibility from tracked local captures; zero requests.

UV_OFFLINE=1 uv run --frozen python -m tools.analysis.measure_document_capture_xml --output /tmp/capture-xml-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spicy_docs.schemas.document_capture.xml import NAMESPACE, decode_capture, encode_capture
from tools.analysis import document_capture as dc


def capture_paths() -> list[Path]:
    """Use Git's inventory so a new fixture anywhere in the repo enters the proof."""
    paths = subprocess.check_output(["git", "ls-files", "-z", "--", "*.capture.json"], cwd=dc.ROOT)
    return [dc.ROOT / name.decode() for name in paths.split(b"\0") if name]


def assert_same_value(expected: Any, actual: Any, path: str = "$") -> None:
    """Compare every field and position, with types and signed float zero intact."""
    assert type(actual) is type(expected), f"{path}: scalar/container type changed"
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys(), f"{path}: object properties changed"
        for key in expected:
            assert_same_value(expected[key], actual[key], f"{path}/{key}")
    elif isinstance(expected, list):
        assert len(expected) == len(actual), f"{path}: array length changed"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            assert_same_value(left, right, f"{path}/{index}")
    elif isinstance(expected, float):
        assert expected.hex() == actual.hex(), f"{path}: float value or sign changed"
    else:
        assert expected == actual, f"{path}: value changed"


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def measure(output: Path) -> dict[str, Any]:
    paths = capture_paths()
    if not paths:
        raise ValueError("no tracked captures")
    output.mkdir(parents=True, exist_ok=False)
    parent, profiles, _ = dc.validators()
    rows = []
    for path in paths:
        data = path.read_bytes()
        capture = json.loads(data)
        parent.validate(capture)
        profiles[capture["profile"]["name"]].validate(capture)
        assert not dc.check_invariants(capture), path
        xml = encode_capture(capture)
        decoded = decode_capture(xml)
        assert_same_value(capture, decoded)
        assert encode_capture(decoded) == xml
        parent.validate(decoded)
        profiles[decoded["profile"]["name"]].validate(decoded)
        assert not dc.check_invariants(decoded), path
        recovered = json_bytes(decoded)
        relative = path.relative_to(dc.ROOT)
        retained = output / relative
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(data)
        retained.with_suffix(".xml").write_bytes(xml)
        retained.with_suffix(".roundtrip.json").write_bytes(recovered)
        rows.append(
            {
                "path": str(relative),
                "sha256": dc.sha256(data),
                "family": capture["profile"]["name"],
                "jsonBytes": len(data),
                "xmlBytes": len(xml),
                "xmlSha256": dc.sha256(xml),
                "decodedJsonBytes": len(recovered),
                "decodedJsonSha256": dc.sha256(recovered),
                "extraBytes": len(xml) - len(data),
                "xmlToJsonRatio": round(len(xml) / len(data), 6),
                "escapedStrings": xml.count(b'encoding="json"'),
                "nodes": len(capture["nodes"]),
                "spans": len(capture["evidence"]),
                "cells": sum(n["kind"] == "cell" for n in capture["nodes"]),
                "equal": True,
                "xmlReencodeEqual": True,
                "parentProfileInvariants": "pass before and after",
            }
        )
    from spicy_docs.schemas.document_capture import xml as codec

    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dc.ROOT, text=True).strip(),
        "command": "UV_OFFLINE=1 uv run --frozen python -m tools.analysis.measure_document_capture_xml --output "
        + str(output),
        "python": sys.version.split()[0],
        "networkRequests": 0,
        "namespace": NAMESPACE,
        "codecSha256": dc.sha256(Path(codec.__file__).read_bytes()),
        "measurementToolSha256": dc.sha256(Path(__file__).read_bytes()),
        "pins": dc.load_schema("PINS.json"),
        "normalization": "none; exact parsed JSON values with scalar types and signed float zero",
        "captures": rows,
    }
    (output / "measurement.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.output)
    for row in report["captures"]:
        print(
            f"{row['family']}: {row['jsonBytes']} JSON -> {row['xmlBytes']} XML -> {row['decodedJsonBytes']} JSON; equal"
        )
    print(f"{len(report['captures'])} captures round-trip; zero requests; no value normalization")


if __name__ == "__main__":
    main()
