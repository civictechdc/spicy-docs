"""Compare fresh PDF captures with independently retained Senate ruled-row readings, offline.

The reference is the pre-existing 80-page table dump passed through the
analytical contract. The other reading freshly extracts the pinned PDF and
uses the capture adapter, never the reference dump's cells. Both readings
share PyMuPDF: this checks preservation, not independent table detection.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from spicy_docs.extraction import DocumentExtractor, NativeText
from spicy_docs.schemas.senate_expenditure_tables import shape_senate_expenditure_rows
from tools.analysis import document_capture as dc
from tools.analysis.document_capture_pdf_tables import convert_senate_pages
from tools.analysis.senate_expenditure_tables import _Observation

RECEIPTS = Path.home() / "Work/corpora/supply-2026-09-02/receipts"
REFERENCE = "senate-expenditure-tables-2026-09-20"
SAMPLES = (("sdoc3-1.p1-80.json", "GPO-CDOC-119sdoc3"), ("sdoc6-2.p1-80.json", "GPO-CDOC-119sdoc6"))


def contract_reading(dump: dict, package_id: str) -> dict:
    rows, cells, positioned = Counter(), Counter(), Counter()
    for page in dump["pages"]:
        for ordinal, table in enumerate(page["tables"]):
            shaped = shape_senate_expenditure_rows(
                _Observation(table, page["page"]),
                page["text"],
                package_id=package_id,
                file_name=dump["file_id"],
                table_ordinal=ordinal,
                page_count=dump["page_count"],
                pages_read=len(dump["pages"]),
                body_rendition="pdf",
                body_derivation="pdf-extraction-lines",
            )
            for row in shaped:
                key = (
                    row["package_id"],
                    row["file_name"],
                    int(row["page"]),
                    int(row["table_ordinal"]),
                    int(row["row_ordinal"]),
                    row["text_sha256"].removeprefix("sha256:"),
                )
                rows[key] += 1
                for column, text in enumerate(json.loads(row["cells_json"])):
                    if text is not None:
                        cell_key = (*key[:5], dc.sha256(text))
                        cells[cell_key] += 1
                        positioned[(*cell_key, column)] += 1
    return {"rows": rows, "cells": cells, "positioned": positioned}


def capture_reading(capture: dict) -> dict:
    rows, cells, positioned = Counter(), Counter(), Counter()
    nodes = {n["id"]: n for n in capture["nodes"]}
    ext = capture["profile"]["ext"]
    for node in capture["nodes"]:
        if node["kind"] not in {"row", "cell"}:
            continue
        row = node if node["kind"] == "row" else nodes[node["parent"]]
        table = nodes[row["parent"]]
        page = nodes[table["parent"]]
        key = (
            ext["packageId"],
            ext["fileName"],
            page["source"]["page"],
            table["ext"]["tableOrdinal"],
            row["ordinal"],
            page["ext"]["pageTextSha256"],
        )
        if node["kind"] == "row":
            rows[key] += 1
        else:
            text = node["ext"]["observedText"]
            # A box without observed text must fail comparison with a missing
            # reference cell, not disappear from the measurement.
            cell_key = (*key[:5], None if text is None else dc.sha256(text))
            cells[cell_key] += 1
            positioned[(*cell_key, node["cell"]["column"])] += 1
    return {"rows": rows, "cells": cells, "positioned": positioned}


def compare_readings(reference: dict, captured: dict) -> dict:
    """Multisets retain duplicate-valued cells; both directional differences can fail."""
    result = {}
    for kind in ("rows", "cells", "positioned"):
        left, right = reference[kind], captured[kind]
        result[kind] = {
            "contract": left.total(),
            "capture": right.total(),
            "matched": (left & right).total(),
            "contractOnly": (left - right).total(),
            "captureOnly": (right - left).total(),
        }
    result["agrees"] = all(
        result[k]["contractOnly"] == result[k]["captureOnly"] == 0 for k in ("rows", "cells", "positioned")
    )
    return result


def measure(receipts: Path, output: Path, sidecar: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    parent, profiles, _ = dc.validators()
    documents = []
    for dump_name, package_id in SAMPLES:
        dump_path = receipts / REFERENCE / dump_name
        dump_bytes = dump_path.read_bytes()
        dump = json.loads(dump_bytes)
        pdf_path = receipts / "pdf-family-rollup-yield-2026-09-20/blobs" / dump["sha256"]
        pdf = pdf_path.read_bytes()
        if dc.sha256(pdf) != dump["sha256"] or len(pdf) != dump["bytes"]:
            raise ValueError(f"PDF differs from retained input pin: {pdf_path}")
        selected = [p["page"] for p in dump["pages"]]
        pages = list(
            DocumentExtractor(NativeText(), tables=True).extract(pdf, media_type="application/pdf", pages=selected)
        )
        conversion = convert_senate_pages(
            pages,
            pdf=pdf,
            pdf_path=pdf_path,
            package_id=package_id,
            file_name=dump["file_id"],
            intermediate_path=output / f"{package_id}.evidence.json",
        )
        capture = conversion.capture()
        capture_path = output / f"{package_id}.capture.json"
        capture_path.write_text(json.dumps(capture, ensure_ascii=False, indent=1) + "\n")
        reference, captured = contract_reading(dump, package_id), capture_reading(capture)
        agreement = compare_readings(reference, captured)
        errors = [e.message for v in (parent, profiles[conversion.family]) for e in v.iter_errors(capture)]
        errors += dc.check_invariants(capture)
        errors += dc.check_profile_composition(
            dc.load_schema(f"profiles/{conversion.family}.schema.json"), parent.schema
        )
        independent, _ = dc.independent_text("evidence-lines", conversion.artifact_bytes, conversion.evidence_json)
        if independent != "".join(s["exact"] for s in capture["evidence"]):
            errors.append("table adaptation changed the line stream")
        cell_nodes = [n for n in capture["nodes"] if n["kind"] == "cell"]
        unresolved = [
            {
                "node": n["id"],
                "page": n["source"]["page"],
                "cell": n["cell"],
                "observedTextSha256": dc.sha256(n["ext"]["observedText"] or ""),
                "reason": i["detail"],
            }
            for n in cell_nodes
            for i in n.get("issues", [])
            if i["code"] == "pdf-cell-text-unresolved"
        ]
        details = {
            "unresolved": unresolved,
            "differences": {
                k: {
                    "contractOnly": [[list(key), count] for key, count in (reference[k] - captured[k]).items()],
                    "captureOnly": [[list(key), count] for key, count in (captured[k] - reference[k]).items()],
                }
                for k in ("rows", "cells", "positioned")
            },
        }
        detail_path = output / f"{package_id}.comparison.json"
        detail_path.write_text(json.dumps(details, ensure_ascii=False, indent=1) + "\n")
        documents.append(
            {
                "packageId": package_id,
                "fileName": dump["file_id"],
                "pdf": {"path": str(pdf_path), "sha256": dc.sha256(pdf), "bytes": len(pdf)},
                "reference": {"path": str(dump_path), "sha256": dc.sha256(dump_bytes)},
                "pagesRead": selected,
                "pageCount": dump["page_count"],
                "tablePages": sum(bool(p.tables) for p in pages),
                "tables": sum(len(p.tables) for p in pages),
                "agreement": agreement,
                "cellsWithSpans": sum(bool(n["evidence"]) for n in cell_nodes),
                "emptyCells": sum(n["ext"]["observedText"] == "" for n in cell_nodes),
                "missingCellSlots": sum(
                    text is None and box is None
                    for p in pages
                    for t in p.tables
                    for row, boxes in zip(t.cells, t.cell_boxes, strict=True)
                    for text, box in zip(row, boxes, strict=True)
                ),
                "cellsWithoutBoxes": sum("box" not in n["source"] for n in cell_nodes),
                "unresolvedCells": len(unresolved),
                "unresolvedReasons": dict(Counter(u["reason"] for u in unresolved)),
                "validationErrors": errors,
                "capture": {"path": str(capture_path), "sha256": dc.sha256(capture_path.read_bytes())},
                "details": {"path": str(detail_path), "sha256": dc.sha256(detail_path.read_bytes())},
            }
        )
    totals = {
        key: sum(d[key] for d in documents)
        for key in (
            "tablePages",
            "tables",
            "cellsWithSpans",
            "emptyCells",
            "missingCellSlots",
            "cellsWithoutBoxes",
            "unresolvedCells",
        )
    }
    totals["pagesRead"] = sum(len(d["pagesRead"]) for d in documents)
    totals["agreement"] = {
        k: {metric: sum(d["agreement"][k][metric] for d in documents) for metric in documents[0]["agreement"][k]}
        for k in ("rows", "cells", "positioned")
    }
    reasons: Counter[str] = Counter()
    for doc in documents:
        reasons.update(doc["unresolvedReasons"])
    totals["unresolvedReasons"] = dict(reasons)
    result = {
        "networkRequests": 0,
        "parentSchema": dc.schema_pin(dc.PARENT_SCHEMA),
        "profileSchema": dc.schema_pin("profiles/senate-expenditures-pdf.schema.json"),
        "implementation": {
            str(p.relative_to(dc.ROOT)): dc.sha256(p.read_bytes())
            for p in (
                Path(__file__),
                dc.ROOT / "tools/analysis/document_capture_pdf_tables.py",
                dc.ROOT / "tools/analysis/document_capture.py",
                dc.ROOT / "src/spicy_docs/schemas/senate_expenditure_tables.py",
            )
        },
        "converter": conversion.converter,
        "documents": documents,
        "totals": totals,
        "passed": all(d["agreement"]["agrees"] and not d["validationErrors"] for d in documents),
    }
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "measurement.json").write_bytes(sidecar.read_bytes())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipts", type=Path, default=RECEIPTS)
    parser.add_argument("--output", type=Path, default=RECEIPTS / "document-capture-pdf-tables-2026-09-20")
    parser.add_argument(
        "--sidecar", type=Path, default=dc.ROOT / "docs/research/document-capture-pdf-tables-2026-09-20.json"
    )
    args = parser.parse_args()
    result = measure(args.receipts, args.output, args.sidecar)
    print(json.dumps({"passed": result["passed"], **result["totals"]}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
