"""Measure what the Secretary of the Senate's ruled tables actually are.

Read-only over bytes the [PDF-family rollup](../../docs/research/pdf-family-rollup-yield-2026-09-20.md)
already retained: the eight Senate expenditure PDFs, content-addressed by
SHA-256 under that measurement's ``blobs/``.  Nothing is fetched, and
``sources/govinfo/`` is not reached at all -- the package-id grammar does not
yet cover ``GPO-CDOC-*``, so acquisition for this family wires up when that
lands and this tool reads the retained bytes until then.

Two phases, both through ``uv run --frozen --all-extras``:

``dump``
    One ``tables=True`` extraction of a bounded page range, every cell text and
    every cell box written out whole, so the shaper is written against what
    PyMuPDF actually returned rather than against a summary of it.

``census``
    Over one or more dumps: how many tables, what their geometry is, which
    grid each one is, how many cells the print actually rules, and how many
    lines parse as amounts.

**The census classifies with the contract's own functions**
(``schemas.senate_expenditure_tables``), never with a second copy of the rules,
so the measurement quoted in
[the note](../../docs/research/senate-expenditure-tables-2026-09-20.md) and the
published rows cannot disagree about what a header row or an amount is.  This
is the same discipline ``interpretation/citations.py`` and
``tools/analysis/pdf_family_rollup.py`` share.

The dumps and the census output are receipts and belong outside the
repository, under ``~/Work/corpora/supply-2026-09-02/receipts/``.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from spicy_docs.schemas.senate_expenditure_tables import parse_amount

#: An office block, counted **without** the contract's grammar: any line the
#: print begins with ``Funding Year``, whatever follows it.  The census
#: otherwise classifies with the contract's own functions, which is what keeps
#: the note and the rows in agreement -- but agreement with itself is not a
#: verification, and a rule that narrowed would report a smaller print and call
#: it correct.  That is exactly how a single-year-only ``Funding Year`` rule
#: shipped reading 78 office pages where the print states 83.
_ANY_FUNDING_YEAR = re.compile(r"^Funding Year\b", re.MULTILINE)

ROLLUP = Path.home() / "Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20"

#: The rollup's retained Senate PDFs, file id to the SHA-256 its
#: ``requests.jsonl`` logged, which is also the blob's name.
RETAINED: dict[str, str] = {
    "GPO-CDOC-119sdoc3.pdf": "eed2f7347dd28d3ae2af19aff495906b474befcb5d9c6f324c2dd768bc6d80b2",
    "GPO-CDOC-119sdoc3-1.pdf": "2248097b0c5106889d8882a979a0488a49f283b29e28289d2778864c40b7b13e",
    "GPO-CDOC-119sdoc5.pdf": "b332e128c82c54f1d377fce1574326b92733b4534be0b7fa642743fd4cc92f41",
    "GPO-CDOC-119sdoc5-1.pdf": "5734ee9a0807fca93559a8c8de5793a5f1f084f670d18b080565cfe695c0c534",
    "GPO-CDOC-119sdoc5-2.pdf": "eab0c9f4cbe138bdf68b76015d813744bd5cb7c5bf31839e7b2f5c79fd6ce593",
    "GPO-CDOC-119sdoc6.pdf": "78a3980b193166e1e82eba53df5ec3134bbcf1f98bb04ee424e223080ad865ff",
    "GPO-CDOC-119sdoc6-1.pdf": "65b5b563cf0cfaf6002eaaa66eff26e8fedd09e6c8e0a00f6e14544ea6691fd8",
    "GPO-CDOC-119sdoc6-2.pdf": "8c0198e57f3f4a3bba56939e3972c7c2d3ef55f4d01aa0addd2457ff98158e47",
}


def dump(file_id: str, pages: list[int]) -> dict:
    """One bounded ``tables=True`` read of a retained volume, cells and boxes whole."""
    from spicy_docs.extraction.api import DocumentExtractor, NativeText

    source = (ROLLUP / "blobs" / RETAINED[file_id]).read_bytes()
    out: dict = {"file_id": file_id, "sha256": RETAINED[file_id], "bytes": len(source), "pages": []}
    extractor = DocumentExtractor(NativeText(), tables=True)
    for result in extractor.extract(source, media_type="application/pdf", pages=pages):
        out["page_count"] = result.metadata["page_count"]
        out["pages"].append(
            {
                "page": result.metadata["page"],
                "geometry": result.metadata["geometry"],
                "text": result.text,
                "tables": [
                    {
                        "bbox": asdict(table.bbox),
                        "row_count": table.row_count,
                        "column_count": table.column_count,
                        "cells": [list(row) for row in table.cells],
                        "cell_boxes": [[None if b is None else asdict(b) for b in row] for row in table.cell_boxes],
                    }
                    for table in result.tables
                ],
            }
        )
    return out


class _Box:
    def __init__(self, box: dict):
        self.x0, self.y0, self.x1, self.y1 = box["x0"], box["y0"], box["x1"], box["y1"]


class _Observation:
    """A dumped table read back as the shape ``TableObservation`` has.

    The dump is JSON, so the contract's structural readers need an object with
    ``cells``, ``page``, ``bbox``, ``row_count`` and ``column_count`` rather
    than a mapping.  Nothing is re-implemented: every rule stays in the schema
    module.
    """

    def __init__(self, table: dict, page: int):
        self.page = page
        self.bbox = _Box(table["bbox"])
        self.row_count = table["row_count"]
        self.column_count = table["column_count"]
        self.cells = tuple(tuple(row) for row in table["cells"])


def census(dumps: list[dict]) -> dict:
    """What the ruled tables are, counted with the contract's own classifiers."""
    from spicy_docs.schemas.senate_expenditure_tables import (
        grid_kind,
        page_context,
        shape_senate_expenditure_rows,
    )

    geometry: Counter[tuple[int, int]] = Counter()
    grids: Counter[str | None] = Counter()
    kinds: Counter[str] = Counter()
    columns: Counter[int] = Counter()
    tables_per_page: Counter[int] = Counter()
    ruled_by_grid: dict[str, Counter[int]] = {}
    amount_lines: Counter[str] = Counter()
    tables = rows = cells = none_cells = amounts = 0
    office_pages = label_pages = table_pages = printed_office_pages = 0
    spans = 0
    per_file: dict[str, dict] = {}
    for one in dumps:
        file_id = one["file_id"]
        mine = per_file.setdefault(file_id, {"pages": 0, "tables": 0, "rows": 0, "amounts": 0})
        for page in one["pages"]:
            mine["pages"] += 1
            tables_per_page[len(page["tables"])] += 1
            if not page["tables"]:
                continue
            table_pages += 1
            context = page_context(page["text"])
            office_pages += context.office is not None
            label_pages += context.printed_page is not None
            spans += context.funding_year_end is not None
            # The independent count, by a reader that knows nothing of the
            # contract's funding-year grammar.
            printed_office_pages += bool(_ANY_FUNDING_YEAR.search(page["text"]))
            for ordinal, table in enumerate(page["tables"]):
                observation = _Observation(table, page["page"])
                tables += 1
                mine["tables"] += 1
                geometry[(observation.row_count, observation.column_count)] += 1
                columns[observation.column_count] += 1
                kind = grid_kind(observation)
                grids[kind] += 1
                shaped = shape_senate_expenditure_rows(
                    observation,
                    page["text"],
                    package_id=file_id.removesuffix(".pdf"),
                    file_name=file_id,
                    table_ordinal=ordinal,
                    page_count=one["page_count"],
                    pages_read=len(one["pages"]),
                    body_rendition="pdf",
                    body_derivation="pdf-extraction-lines",
                    context=context,
                )
                for row, shaped_row in zip(observation.cells, shaped, strict=True):
                    rows += 1
                    mine["rows"] += 1
                    kinds[shaped_row["row_kind"]] += 1
                    present = sum(1 for cell in row if cell is not None)
                    if shaped_row["row_kind"] == "entry" and kind is not None:
                        ruled_by_grid.setdefault(kind, Counter())[present] += 1
                    cells += len(row)
                    none_cells += len(row) - present
                    amounts += int(shaped_row["amount_count"])
                    mine["amounts"] += int(shaped_row["amount_count"])
                for row in observation.cells:
                    for cell in row:
                        for line in (cell or "").split("\n"):
                            if parse_amount(line) is not None:
                                amount_lines[line.strip()] += 1
    shapes = sorted(geometry)
    return {
        "files": per_file,
        "pages": sum(one["pages"] for one in per_file.values()),
        "pages_with_a_table": table_pages,
        "tables": tables,
        "tables_per_page": dict(sorted(tables_per_page.items())),
        "grid_kinds": dict(sorted(grids.items(), key=lambda pair: str(pair[0]))),
        "rows": rows,
        "row_kinds": dict(sorted(kinds.items())),
        "cells": cells,
        "cells_with_no_region": none_cells,
        "entry_row_cells_present_by_grid": {
            grid: dict(sorted(counts.items())) for grid, counts in sorted(ruled_by_grid.items())
        },
        "amounts": amounts,
        "distinct_amount_spellings": len(amount_lines),
        "column_counts": dict(sorted(columns.items())),
        "geometry_min_rows_columns": list(shapes[0]) if shapes else None,
        "geometry_max_rows_columns": list(shapes[-1]) if shapes else None,
        "distinct_geometries": len(geometry),
        # These two must agree.  The first is what `page_context` read, the
        # second what the print states, counted by a reader that shares none of
        # its grammar; a gap means the contract's rule is narrower than the
        # print and some pages lost their office silently.
        "table_pages_stating_an_office": office_pages,
        "table_pages_the_print_states_an_office_on": printed_office_pages,
        "table_pages_with_a_multi_year_funding_span": spans,
        "table_pages_stating_a_printed_page": label_pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    one = sub.add_parser("dump")
    one.add_argument("file_id", choices=sorted(RETAINED))
    one.add_argument("first", type=int)
    one.add_argument("last", type=int)
    one.add_argument("out", type=Path)
    many = sub.add_parser("census")
    many.add_argument("dumps", type=Path, nargs="+")
    many.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.phase == "dump":
        args.out.write_text(json.dumps(dump(args.file_id, list(range(args.first, args.last + 1))), indent=1))
        print(f"{args.file_id} pages {args.first}-{args.last} -> {args.out}")
    else:
        report = census([json.loads(path.read_text()) for path in args.dumps])
        rendered = json.dumps(report, indent=1)
        if args.out:
            args.out.write_text(rendered)
        print(rendered)


if __name__ == "__main__":
    main()
