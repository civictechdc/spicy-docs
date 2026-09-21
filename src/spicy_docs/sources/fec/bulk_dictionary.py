"""Read the FEC's ordered bulk-field table from retained HTML evidence."""

from __future__ import annotations

import hashlib
import re

from spicy_docs.reading.markup import read_html_events

MAX_DICTIONARY_BYTES = 8 * 1024**2
_HEADERS = ("Column name", "Field name", "Position")


def parse_bulk_dictionary(raw: bytes, *, sha256: str) -> dict:
    """Return one unambiguous ordered dictionary with literal cell evidence.

    HTML permits omitted cell/row end tags, so the next cell/row start closes
    the preceding one. This recognizes only the publisher's explicit table
    headings and consecutive one-based positions. It does not choose the file,
    cycle, field types or amendment rules to which a caller applies the table.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_DICTIONARY_BYTES:
        raise ValueError("FEC dictionary must be bounded retained bytes")
    if sha256 != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("FEC dictionary digest differs from retained bytes")
    tables, table, row, cell = [], None, None, None

    def finish_cell():
        nonlocal cell
        if cell is not None:
            cell["text"] = "".join(fragment["text"] for fragment in cell["fragments"])
            row["cells"].append(cell)
            cell = None

    def finish_row():
        nonlocal row
        finish_cell()
        if row is not None:
            table["rows"].append(row)
            row = None

    for event in read_html_events(raw, max_bytes=MAX_DICTIONARY_BYTES).events:
        if event.kind == "start" and event.name == "table":
            if table is not None:
                raise ValueError("nested FEC dictionary tables are ambiguous")
            table = {"locator": {"table_ordinal": len(tables), "byte_start": event.byte_start}, "rows": []}
        elif event.kind == "end" and event.name == "table" and table is not None:
            finish_row()
            tables.append(table)
            table = None
        elif table is not None and event.kind == "start" and event.name == "tr":
            finish_row()
            row = {"locator": {"row_ordinal": len(table["rows"]), "byte_start": event.byte_start}, "cells": []}
        elif table is not None and event.kind == "end" and event.name == "tr":
            finish_row()
        elif table is not None and event.kind == "start" and event.name in {"td", "th"}:
            if row is None:
                raise ValueError("FEC dictionary cell has no explicit source row")
            finish_cell()
            if any(name in {"rowspan", "colspan"} and value != "1" for name, value in event.attributes):
                raise ValueError("spanning FEC dictionary cells are ambiguous")
            cell = {"locator": {"cell_ordinal": len(row["cells"]), "byte_start": event.byte_start}, "fragments": []}
        elif table is not None and event.kind == "end" and event.name in {"td", "th"}:
            finish_cell()
        elif cell is not None and event.kind == "text":
            cell["fragments"].append(
                {
                    "text": event.text,
                    "byte_start": event.byte_start,
                    "byte_end": event.byte_end,
                    "is_literal": event.is_literal,
                }
            )
    if table is not None:
        raise ValueError("FEC dictionary table is not closed")
    candidates = [
        table
        for table in tables
        if table["rows"] and tuple(cell["text"].strip() for cell in table["rows"][0]["cells"][:3]) == _HEADERS
    ]
    if len(candidates) != 1:
        raise ValueError("expected exactly one FEC ordered field dictionary table")
    selected = candidates[0]
    header = selected["rows"][0]
    definitions = []
    names = set()
    for position, source_row in enumerate(selected["rows"][1:], 1):
        cells = source_row["cells"]
        if len(cells) != len(header["cells"]):
            raise ValueError("FEC dictionary row width differs from its headings")
        name = cells[0]["text"].strip()
        native_position = cells[2]["text"].strip()
        if not name or name in names:
            raise ValueError("FEC dictionary field names must be nonempty and unique")
        if re.fullmatch(r"[0-9]+", native_position) is None or int(native_position) != position:
            raise ValueError("FEC dictionary positions must be consecutive from one")
        names.add(name)
        definitions.append({"name": name, "position": position, "locator": source_row["locator"], "cells": cells})
    if not definitions:
        raise ValueError("FEC dictionary has no field definitions")
    return {
        "source_sha256": sha256,
        "byte_size": len(raw),
        "table_locator": selected["locator"],
        "header_cells": header["cells"],
        "fields": definitions,
    }
