"""Known source drift and independent XLSX-cell replay for literal filing labels."""

import copy
import hashlib
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest

from spicy_docs.sources.fec import layouts

FIXTURES = Path(__file__).parent / "fixtures/fec/layouts"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def source_cells(path):
    """Independent XML read of these pinned workbooks; no OpenPyXL or generator."""
    with zipfile.ZipFile(path) as archive:
        strings = [
            "".join(t.text or "" for t in item.findall(".//m:t", NS))
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)
        ]
        relationships = {
            r.attrib["Id"]: posixpath.normpath("xl/" + r.attrib["Target"])
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        result, formulas = {}, {}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            rows = ET.fromstring(archive.read(relationships[rid]))
            cells = {}
            formula_cells = {}
            for cell in rows.findall(".//m:c", NS):
                value = cell.find("m:v", NS)
                text = value.text if value is not None else None
                if cell.get("t") == "s" and text is not None:
                    text = strings[int(text)]
                cells[cell.attrib["r"]] = text
                formula = cell.find("m:f", NS)
                if formula is not None:
                    formula_cells[cell.attrib["r"]] = {"text": formula.text, "attributes": dict(formula.attrib)}
            result[sheet.attrib["name"]] = cells
            formulas[sheet.attrib["name"]] = formula_cells
        return result, formulas


def test_every_packaged_label_and_selector_matches_its_pinned_source_cell():
    catalog = json.loads(files("spicy_docs.sources.fec").joinpath("field_layouts.json").read_bytes())
    workbooks, formulas = [], []
    for source in catalog["sources"]:
        path = FIXTURES / source["file"]
        raw = path.read_bytes()
        assert len(raw) == source["bytes"]
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == source["sha256"]
        cells, formula_cells = source_cells(path)
        workbooks.append(cells)
        formulas.append(formula_cells)
    expected, actual = set(), set()
    for source_index, workbook in enumerate(workbooks):
        for name, cells in workbook.items():
            if name in {"NOTE", "all versions", "Version 8.5", "SUMMARY OF CHANGES"}:
                continue
            for cell, value in cells.items():
                match = re.fullmatch(r"A(\d+)", cell)
                if not match or value is None:
                    continue
                row = int(match[1])
                if source_index == 1 and value.isdigit():
                    expected.add((source_index, name, None))
                elif source_index != 1 and value.startswith("v"):
                    expected.add((source_index, name, row))
    for layout in catalog["layouts"]:
        actual.add((layout["source_index"], layout["sheet"], layout["row"]))
        workbook = workbooks[layout["source_index"]]
        cells = workbook[layout["sheet"]]
        if layout["row"] is None:
            assert workbook["HDR"]["E7"] == layout["version"]
        else:
            assert cells[layout["version_cell"]] == layout["version"]
            assert cells[layout["form_cell"]] == layout["form"]
        for index, definition in enumerate(layout["fields"]):
            position = re.fullmatch(r"([A-Z]+)(\d+)", definition["cell"])
            assert position is not None
            if layout["row"] is None:
                assert position[1] == "B" and cells["A" + position[2]] == str(index + 1)
            else:
                column = 0
                for letter in position[1]:
                    column = column * 26 + ord(letter) - ord("A") + 1
                assert column == index + 3 and int(position[2]) == layout["row"]
            assert cells.get(definition["cell"]) == definition["label"]
            source_formulas = formulas[layout["source_index"]][layout["sheet"]]
            formula = source_formulas.get(definition["cell"])
            if formula is None:
                assert "formula" not in definition
            elif formula["text"]:
                assert definition["formula"] == "=" + formula["text"]
            else:
                # Check the pinned shared formula's relative columns without an evaluator.
                assert layout["sheet"] == "SH3" and formula["attributes"]["t"] == "shared"
                anchor = [
                    f
                    for f in source_formulas.values()
                    if f["attributes"].get("si") == formula["attributes"]["si"] and f["text"]
                ]
                assert len(anchor) == 1 and anchor[0]["text"] == 'CONCATENATE(N11,"-",N12)'
                column = definition["cell"].removesuffix("15")
                assert definition["formula"] == f'=CONCATENATE({column}11,"-",{column}12)'
        if layout["row"] is None:
            positions = [
                int(value) for cell, value in cells.items() if re.fullmatch(r"A\d+", cell) and value and value.isdigit()
            ]
            assert positions == list(range(1, len(layout["fields"]) + 1))
        else:
            columns = []
            for cell, value in cells.items():
                match = re.fullmatch(r"([A-Z]+)" + str(layout["row"]), cell)
                if match and value is not None:
                    column = 0
                    for letter in match[1]:
                        column = column * 26 + ord(letter) - ord("A") + 1
                    columns.append(column)
            assert max(columns) - 2 == len(layout["fields"])
        for note in layout.get("notes", []):
            assert note["sheet"] in workbook and note["row"] > 0
    assert actual == expected


def select(version="8.5", form="Text", family="electronic", **kwargs):
    return layouts.filing_layout(family=family, version=version, form=form, **kwargs)


def record(values):
    return {
        "kind": "record",
        "record_type": values[0] if values else "",
        "field_count": len(values),
        "fields": {str(i): v for i, v in enumerate(values)},
        "embedded_bodies": [],
        "source": {"sha256": "sha256:" + "a" * 64, "byte_offset": 10, "byte_length": 20},
        "future_member": {"literal": ["retain"]},
    }


def test_same_width_historical_layouts_keep_different_meanings_and_literal_versions():
    old, new = select("v5.3", "SL"), select("v8.1", "SL")
    assert len(old["fields"]) == len(new["fields"]) == 41
    assert old["fields"][2]["label"] == "3-NAME OF ACCOUNT"
    assert new["fields"][2]["label"] == "3-TRANSACTION ID NUMBER"
    for version in ("5.3", "v5.30", "3.00"):
        with pytest.raises(KeyError):
            select(version, "SL")
    assert select("v3.3", "F132", "paper")["fields"][2]["label"] == "3 -  CONTRIB ORGANIZATION NAME"
    assert select("v8.4", "F132")["fields"][2]["label"] == "3-TRANSACTION ID NUMBER"


def test_ambiguous_dictionary_rows_never_overwrite_or_choose_a_winner():
    with pytest.raises(ValueError, match="multiple layouts"):
        select("v6.4", "F3S")
    assert len(select("v6.4", "F3S", row=7)["fields"]) == 35
    assert len(select("v6.4", "F3S", row=8)["fields"]) == 90
    choices = [x["row"] for x in layouts.filing_layouts() if x["version"] == "v6.4" and x["form"] == "F3S"]
    assert choices == [7, 8]


def test_duplicate_printed_ordinals_remain_separate_positions():
    fields = select("v3", "SI")["fields"]
    assert fields[13] == {"label": "15-8. Receipts", "cell": "P10"}
    assert fields[14] == {"label": "15-9. Subtotal", "cell": "Q10"}


def test_formula_labels_retain_publisher_cache_and_unevaluated_formula():
    fields = select("v3", "SH3")["fields"]
    assert fields[11] == {"label": "-", "cell": "N15", "formula": '=CONCATENATE(N11,"-",N12)'}


def test_excluded_sheet_notes_survive_without_guessed_form_joins():
    layout = select(form="F3Z1")
    notes = {n["row"]: n["cells"] for n in layout["source"]["notes"]}
    assert notes[12][0] == "F3Z 1"
    assert "Excluded from format specifications" in notes[12][1]
    assert notes[42][0] == "SC2 " and "Added Line Numbers 5, 6 & 7" in notes[42][1]


def test_mapping_preserves_blanks_values_extras_unknown_members_and_body_references():
    layout = select()
    original = record(["TEXT", "C00000001", "T1", "", "F99", "body", "EXTRA", ""])
    body = {**original["source"], "field_index": 5, "delimiter": "\x1c", "encoding": "utf-8"}
    original["embedded_bodies"] = [body]
    del original["fields"]["5"]
    before = copy.deepcopy(original)
    result = layouts.map_filing_fields(original, layout=layout, format_version="8.5")
    assert {k: result[k] for k in original} == original == before
    assert result["declared_format_version"] == "8.5"
    mapping = result["field_mapping"]
    assert mapping["selection"] == "caller-selected" and mapping["width"] == "extra_fields"
    assert mapping["annotations"][5]["presence"] == "body"
    assert set(mapping["annotations"][5]["definition"]) == {"label", "cell"}
    assert "notes" not in mapping["layout"] and "notes" not in mapping["layout"]["source"]
    assert "notes" in layout["source"] and "specification" in layout["fields"][0]
    assert mapping["annotations"][6:] == [
        {"index": 6, "presence": "value", "definition": None},
        {"index": 7, "presence": "value", "definition": None},
    ]
    assert result["fields"]["3"] == result["fields"]["7"] == ""
    result["future_member"]["literal"].append("change copy")
    assert original == before


def test_short_records_keep_absent_positions_distinct_from_blank_and_zero():
    result = layouts.map_filing_fields(record(["TEXT", "", "0"]), layout=select(), format_version="8.5")
    mapping = result["field_mapping"]
    assert mapping["width"] == "short"
    assert [x["presence"] for x in mapping["annotations"]] == ["value"] * 3 + ["absent"] * 3
    assert result["fields"] == {"0": "TEXT", "1": "", "2": "0"}


def test_selection_does_not_claim_compatibility_or_coerce_native_versions():
    result = layouts.map_filing_fields(record(["H5", "-01.00"]), layout=select("v5.3", "SH5"), format_version="5.00")
    assert result["record_type"] == "H5" and result["declared_format_version"] == "5.00"
    assert result["fields"]["1"] == "-01.00" and result["field_mapping"]["selection"] == "caller-selected"


def test_layout_copies_cannot_change_the_registry_or_later_mappings():
    first = select()
    first["fields"][0]["label"] = "changed"
    assert select()["fields"][0]["label"] == "REC TYPE"


@pytest.mark.parametrize("member", ["declared_format_version", "field_mapping"])
def test_output_member_collisions_are_explicit(member):
    row = record(["TEXT"])
    row[member] = "retain"
    with pytest.raises(ValueError, match="already contains"):
        layouts.map_filing_fields(row, layout=select(), format_version="8.5")


def test_mapping_bounds_and_partition_checks_fire_before_iterating_malformed_inputs():
    layout = select()
    row = record(["TEXT"] * 6)
    assert layouts.map_filing_fields(row, layout=layout, format_version="8.5", max_fields=6)
    with pytest.raises(ValueError, match="max_fields"):
        layouts.map_filing_fields(row, layout=layout, format_version="8.5", max_fields=5)

    class MustNotIterate(list):
        def __iter__(self):
            raise AssertionError("size refusal must precede iteration")

    row["embedded_bodies"] = MustNotIterate([{}] * 7)
    with pytest.raises(ValueError, match="each position"):
        layouts.map_filing_fields(row, layout=layout, format_version="8.5")
    row = record(["TEXT", "value"])
    row["fields"] = {"0": "TEXT", "2": "wrong position"}
    with pytest.raises(ValueError, match="each position"):
        layouts.map_filing_fields(row, layout=layout, format_version="8.5")


def test_mapping_selected_layout_never_reloads_the_registry(monkeypatch):
    layout = select()
    monkeypatch.setattr(layouts, "_catalog", lambda: pytest.fail("registry accessed per record"))
    for _ in range(3):
        assert layouts.map_filing_fields(record(["TEXT"]), layout=layout, format_version="8.5")
