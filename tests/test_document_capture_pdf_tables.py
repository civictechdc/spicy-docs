"""Real retained PDF observations, exact ownership, and a comparison that can fail."""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import asdict, replace

import pytest

from spicy_docs.extraction import DocumentExtractor, NativeText
from spicy_docs.extraction.model import Box, Observation, PageContent, PageResult, TableObservation, TextBlock
from tools.analysis import document_capture as dc
from tools.analysis import document_capture_pdf_tables as pdf_tables
from tools.analysis.measure_document_capture_pdf_tables import capture_reading, compare_readings, contract_reading

FIXTURE = dc.FIXTURES / "document_capture_pdf_tables"


@pytest.fixture(scope="module")
def page():
    source = json.loads((FIXTURE / "source.json").read_text())
    pdf = (FIXTURE / source["fixture"]).read_bytes()
    assert dc.sha256(pdf) == source["sha256"]
    return next(DocumentExtractor(NativeText(), tables=True).extract(pdf, media_type="application/pdf"))


def build(page, tmp_path):
    source = json.loads((FIXTURE / "source.json").read_text())
    path = FIXTURE / source["fixture"]
    return pdf_tables.convert_senate_pages(
        [page],
        pdf=path.read_bytes(),
        pdf_path=path,
        package_id=source["package_id"],
        file_name=source["source_file"],
        intermediate_path=tmp_path / "evidence.json",
    ).capture()


def test_real_page_kinds_geometry_empty_missing_and_unresolved(page, tmp_path):
    capture = build(page, tmp_path)
    kinds = Counter(n["kind"] for n in capture["nodes"])
    assert kinds["table"] == 1
    assert kinds["row"] == 3
    assert kinds["cell"] == 19
    nodes = [n for n in capture["nodes"] if n["kind"] == "cell"]
    cells = {(n["cell"]["row"], n["cell"]["column"]): n for n in nodes}
    table = page.tables[0]
    for r, row in enumerate(table.cells):
        for c, text in enumerate(row):
            if text is None:
                assert (r, c) not in cells
                continue
            node = cells[r, c]
            assert node["ext"]["observedText"] == text
            assert node["source"] == pdf_tables.source_box(1, table.cell_boxes[r][c])
            assert set(node["cell"]) == {"row", "column"}  # no inferred header or spans
    assert cells[2, 1]["ext"]["observedText"] == cells[2, 1]["text"] == ""
    assert cells[2, 1]["evidence"] == []
    assert cells[0, 0]["source"]["box"] == [860, 329, 915, 520]
    assert cells[0, 0]["text"] == "APPROPRIATION TITLE"
    absent = cells[0, 6]
    assert absent["ext"]["observedText"] == "NET\nEXPENDITURES"
    assert absent["evidence"] == []
    assert absent["reviewStatus"] == "needs_review"
    assert {i["code"] for i in absent["issues"]} >= {"pdf-cell-text-unresolved", "pdf-cell-box-missing"}
    assert any(i.get("detail") == "text-not-in-page-stream" for i in absent["issues"])
    assert capture["unresolved"] == []  # the schema forbids a region without existing spans
    spans = {s["id"]: s for s in capture["evidence"]}
    for cell in nodes:
        if cell["evidence"]:
            assert "".join(spans[s]["exact"] for s in cell["evidence"]) == cell["ext"]["observedText"]
    parent, profiles, _ = dc.validators()
    parent.validate(capture)
    profiles["senate-expenditures-pdf"].validate(capture)
    assert dc.check_invariants(capture) == []
    independent, _ = dc.independent_text("evidence-lines", b"", json.loads((tmp_path / "evidence.json").read_text()))
    assert "".join(s["exact"] for s in capture["evidence"]) == independent


@pytest.mark.parametrize(
    "mutation",
    ("change", "drop", "duplicate", "column", "package", "file", "page", "table", "row", "page-text-digest"),
)
def test_comparison_refuses_changed_missing_duplicate_moved_and_misidentified_cells(page, tmp_path, mutation):
    # Separate extraction from the same fixture bytes, then the analytical
    # shaper. Never feed capture-owned observations into the reference.
    source = json.loads((FIXTURE / "source.json").read_text())
    again = next(
        DocumentExtractor(NativeText(), tables=True).extract(
            (FIXTURE / source["fixture"]).read_bytes(), media_type="application/pdf"
        )
    )
    dump = {
        "file_id": source["source_file"],
        "page_count": 1,
        "pages": [{"page": 1, "text": again.text, "tables": [asdict(t) for t in again.tables]}],
    }
    reference = contract_reading(dump, source["package_id"])
    capture = build(page, tmp_path)
    assert compare_readings(reference, capture_reading(capture))["agrees"]
    broken = copy.deepcopy(capture)
    node = next(n for n in broken["nodes"] if n["kind"] == "cell")
    if mutation == "change":
        node["ext"]["observedText"] += " changed"
    elif mutation == "drop":
        broken["nodes"].remove(node)
    elif mutation == "duplicate":
        broken["nodes"].append(copy.deepcopy(node))
    elif mutation == "column":
        node["cell"]["column"] += 1
    elif mutation in {"package", "file"}:
        key = "packageId" if mutation == "package" else "fileName"
        broken["profile"]["ext"][key] += " changed"
    elif mutation == "table":
        next(n for n in broken["nodes"] if n["kind"] == "table")["ext"]["tableOrdinal"] += 1
    elif mutation == "row":
        next(n for n in broken["nodes"] if n["kind"] == "row")["ordinal"] += 1
    else:
        p = next(n for n in broken["nodes"] if n["kind"] == "page")
        if mutation == "page":
            p["source"]["page"] += 1
        else:
            p["ext"]["pageTextSha256"] = "0" * 64
    result = compare_readings(reference, capture_reading(broken))
    assert not result["agrees"], mutation


def synthetic(texts, line_text="same same", boxes=None):
    box = Box(0, 0, 1, 1)
    blocks = (TextBlock(line_text, box, observation="native"),)
    raw = {"blocks": [{"lines": [{"spans": [{"text": line_text}]}]}]}
    table = TableObservation(1, box, 1, len(texts), (tuple(texts),), (tuple(boxes or [box] * len(texts)),))
    page = PageResult(
        {"page": 1, "page_count": 1, "geometry": {"display_rect": [0, 0, 100, 100]}},
        PageContent(blocks, (Observation("native", line_text, {}, raw, blocks),)),
        (table,),
    )
    builder = dc.Builder(dc.Node("document", None, "pdf-text", container=True))
    pdf_tables.pdf_pages_to_nodes([page], builder)
    return builder


def test_ambiguous_and_overlapping_claims_never_choose_first():
    for texts, line, reason in [
        (["same"], "same same", "ambiguous-page-text"),
        (["same", "same"], "same", "overlapping-cell-claims"),
        (["0.00"], "30.00", "text-not-in-page-stream"),
    ]:
        builder = synthetic(texts, line)
        nodes, stream = builder.finish()
        assert stream == line
        cells = [n for n in nodes if n.kind == "cell"]
        assert all(not n.spans for n in cells)
        assert all(any(i.get("detail") == reason for i in n.issues) for n in cells)


def test_exact_match_splits_and_transfers_without_duplicate_ownership():
    builder = synthetic(["alpha", "beta"], "prefix alpha beta suffix")
    nodes, stream = builder.finish()
    assert stream == "prefix alpha beta suffix"
    assert [n.text for n in nodes if n.kind == "cell"] == ["alpha", "beta"]
    assert [n.text for n in nodes if n.kind == "line"] == ["prefix   suffix"]
    assert Counter(id(s) for n in nodes for s in n.spans) == Counter(id(s) for s in builder.spans)
    assert [s.start for s in builder.spans] == [0, 7, 12, 13, 17]


@pytest.mark.parametrize(
    ("texts", "line", "resolved"),
    [
        (["one two three", "one", "two", "three", "three four", "four", "safe"], "one two three four safe", ["safe"]),
        (["a ", "b"], "a b", ["a ", "b"]),
        (["same"] * 500, "same", []),
    ],
    ids=("nested-and-chained-overlaps", "touching-claims", "duplicate-claims"),
)
def test_overlap_components_refuse_every_participant_but_keep_disjoint_claims(texts, line, resolved):
    builder = synthetic(texts, line)
    nodes, stream = builder.finish()
    assert stream == line
    cells = [n for n in nodes if n.kind == "cell"]
    assert [n.text for n in cells if n.spans] == resolved
    for cell in cells:
        if not cell.spans:
            assert {"code": "pdf-cell-text-unresolved", "detail": "overlapping-cell-claims"} in cell.issues
    assert Counter(id(s) for n in nodes for s in n.spans) == Counter(id(s) for s in builder.spans)


def test_multiple_pages_keep_text_offsets_ownership_and_empty_pages(page):
    pages = [
        replace(
            page,
            metadata={**page.metadata, "page": number, "page_count": 4},
            tables=tuple(replace(t, page=number) for t in page.tables) if number in (1, 4) else (),
        )
        for number in range(1, 5)
    ]
    pages[2] = replace(pages[2], content=PageContent((), (Observation("native", "", {}, {"blocks": []}, ()),)))
    builder = dc.Builder(dc.Node("document", None, "pdf-text", container=True))
    evidence = pdf_tables.pdf_pages_to_nodes(pages, builder)
    nodes, stream = builder.finish()
    independent, _ = dc.independent_text("evidence-lines", b"", evidence)
    assert stream == independent
    assert stream.count("\f") == 2  # the empty page adds no evidence separator
    assert [n.source["page"] for n in nodes if n.kind == "page"] == [1, 2, 3, 4]
    assert Counter(id(s) for n in nodes for s in n.spans) == Counter(id(s) for s in builder.spans)
    assert all(stream[s.start : s.end] == s.exact for s in builder.spans)
    cells = [n for n in nodes if n.kind == "cell"]
    first, last = [n for n in cells if n.source["page"] == 1], [n for n in cells if n.source["page"] == 4]
    assert [(n.text, n.ext, n.issues) for n in first] == [(n.text, n.ext, n.issues) for n in last]
    assert all(s.source.get("page") in (None, n.source["page"]) for n in cells for s in n.spans)


def test_no_line_page_and_box_without_text_survive():
    builder = synthetic(["", None], "", [Box(0, 0, 0.5, 1), Box(0.5, 0, 1, 1)])
    nodes, stream = builder.finish()
    assert stream == ""
    cells = [n for n in nodes if n.kind == "cell"]
    assert len(cells) == 2
    assert cells[0].ext == {"observedText": ""}
    assert cells[1].ext == {"observedText": None}
    assert any(i.get("detail") == "cell-text-missing" for i in cells[1].issues)


def test_cell_text_does_not_match_another_page(page, tmp_path):
    table = page.tables[0]
    changed = replace(table, cells=(("ONLY ON ANOTHER PAGE", *table.cells[0][1:]), *table.cells[1:]))
    modified = replace(page, tables=(changed,))
    text = "ONLY ON ANOTHER PAGE"
    blocks = (TextBlock(text, Box(0, 0, 1, 1), observation="native"),)
    raw = {"blocks": [{"lines": [{"spans": [{"text": text}]}]}]}
    other = replace(
        page,
        metadata={**page.metadata, "page": 2},
        tables=(),
        content=PageContent(blocks, (Observation("native", text, {}, raw, blocks),)),
    )
    builder = dc.Builder(dc.Node("document", None, "pdf-text", container=True))
    pdf_tables.pdf_pages_to_nodes([modified, other], builder)
    nodes, stream = builder.finish()
    node = next(n for n in nodes if n.kind == "cell")
    assert stream.endswith(text)
    assert node.ext == {"observedText": text}
    assert node.spans == []
    assert any(i.get("detail") == "text-not-in-page-stream" for i in node.issues)
