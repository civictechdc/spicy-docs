"""Bounded candidates from the visually reviewed Senate B payment-grid layout.

Header cell geometry assigns columns; native word positions assign lines. Only
page-local, explicitly printed office context is used. Unpriced continuation
text, summaries, negative payment lines and unfamiliar layouts are retained as
refusals. Candidates are not a complete statement or publication qualification.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Any

from spicy_docs.reading.senate_payment_review import review_pages
from spicy_docs.schemas.senate_expenditure_tables import parse_amount

RULE = "senate-b-payment-candidates/1"
MAX_BYTES = 16 * 1024 * 1024
MAX_PAGES = 8
MAX_WORDS_PER_PAGE = 5_000
MAX_CANDIDATES = 2_000
HEADERS = {
    "DOCUMENT NO.": "document",
    "DATE POSTED": "date_posted",
    "PAYEE NAME": "payee",
    "DESCRIPTION": "description",
    "AMOUNT ($)": "amount",
    "START": "service_start",
    "END": "service_end",
}
FIELDS = ("document", "date_posted", "payee", "service_start", "service_end", "description", "amount")
DOCUMENT = re.compile(r"DJST[0-9]{8}\Z")  # Positive native document family in the reviewed grid.


def _date(value: str) -> date | None:
    if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", value):
        return None
    try:
        month, day, year = map(int, value.split("/"))
        return date(year, month, day)
    except ValueError:
        return None


def _header(table: Any) -> tuple[dict, float] | None:
    """Read the ruled two-band header; do not infer column edges from label width."""
    cells = table.extract()
    for row_index, row in enumerate(cells[:-1]):
        if "DOCUMENT NO." not in [" ".join((value or "").split()) for value in row]:
            continue
        bands = {}
        for index in (row_index, row_index + 1):
            for text, box in zip(cells[index], table.rows[index].cells, strict=True):
                label = " ".join((text or "").split())
                if label in HEADERS and box is not None:
                    field = HEADERS[label]
                    if field in bands:
                        return None
                    bands[field] = list(box)
        if set(bands) != set(FIELDS):
            return None
        ordered = [bands[field] for field in FIELDS]
        if any(left[2] > right[0] + 0.5 for left, right in pairwise(ordered)):
            return None
        return bands, max(box[3] for box in ordered)
    return None


def payment_candidates(body: bytes, *, pages: Sequence[int], source_page_offset: int = 0) -> dict[str, Any]:
    """Read selected retained pages, never fetch or silently carry context across pages.

    ``source_page_offset`` is explicit cut-file provenance checked by the caller.
    Output retains the raw review capture, candidate fields, source word indices,
    native and display boxes, header cells, refusals and per-page coverage. The
    only amount sum is labeled selected candidates, never a reconciled total.
    """
    import pymupdf

    if len(body) > MAX_BYTES or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("Payment candidate input exceeds its byte or page bound")
    # Bound word extraction before the table reader allocates review structures.
    with pymupdf.open(stream=body, filetype="pdf") as document:
        for number in pages:
            if type(number) is not int or not 1 <= number <= len(document):
                raise ValueError("Candidate page is outside the retained PDF")
            if len(document[number - 1].get_text("words")) > MAX_WORDS_PER_PAGE:
                raise ValueError("Candidate page exceeds the native word bound")
    capture = review_pages(body, pages=pages, source_page_offset=source_page_offset)
    result: dict[str, Any] = {
        "rule": RULE,
        "input_sha256": capture["input_sha256"],
        "capture": capture,
        "candidates": [],
        "refusals": [],
        "pages": [],
        "publication_qualified": False,
    }
    with pymupdf.open(stream=body, filetype="pdf") as document:
        for number in pages:
            page = capture["pages"][str(number)]
            context = page["context"]
            provenance = {"page": number, "source_page": page["source_page"], "printed_page": context["printed_page"]}
            before = len(result["candidates"])
            page_refusals = len(result["refusals"])

            def refuse(reason, _provenance=provenance, **detail):
                result["refusals"].append({**_provenance, "reason": reason, **detail})

            if page["rotation"] != 90 or not str(context["printed_page"] or "").startswith("B-"):
                refuse("unsupported_layout")
                result["pages"].append({**provenance, "status": "unsupported_layout", "candidates": 0})
                continue
            if not context["office"]:
                refuse("office_not_stated_on_page", word_indices=list(range(len(page["words"]))))
                result["pages"].append({**provenance, "status": "unqualified_office_context", "candidates": 0})
                continue
            native = document[number - 1]
            grids = [(table, header) for table in native.find_tables().tables if (header := _header(table))]
            if len(grids) != 1:
                refuse("missing_or_ambiguous_payment_header")
                result["pages"].append({**provenance, "status": "unsupported_header", "candidates": 0})
                continue
            table, (bands, top) = grids[0]
            office_words = context["office"].split()
            office_spans = [
                list(range(i, i + len(office_words)))
                for i in range(len(page["words"]))
                if [w["text"] for w in page["words"][i : i + len(office_words)]] == office_words
            ]
            if len(office_spans) != 1 or any(
                (pymupdf.Rect(page["words"][i]["bbox"]) * native.rotation_matrix).y1 >= top for i in office_spans[0]
            ):
                refuse("office_origin_not_uniquely_above_header")
                result["pages"].append({**provenance, "status": "unqualified_office_context", "candidates": 0})
                continue
            words = []
            outside = []
            for index, word in enumerate(page["words"]):
                box = list(pymupdf.Rect(word["bbox"]) * native.rotation_matrix)
                x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                if top < y < table.bbox[3] and table.bbox[0] <= x <= table.bbox[2]:
                    words.append({**word, "index": index, "display_bbox": box, "x": x, "y": y})
                else:
                    outside.append(index)
            refuse("outside_payment_body", word_indices=outside)
            lines: list[list[dict]] = []
            for word in sorted(words, key=lambda word: (word["y"], word["x"])):
                if not lines or abs(word["y"] - lines[-1][0]["y"]) > 1.0:
                    lines.append([])
                lines[-1].append(word)
            group = None
            ordinal = 0
            for line in lines:
                columns = {field: [] for field in FIELDS}
                ambiguous = False
                for word in sorted(line, key=lambda word: word["x"]):
                    matches = [field for field, box in bands.items() if box[0] <= word["x"] < box[2]]
                    if len(matches) != 1:
                        ambiguous = True
                        continue
                    field = matches[0]
                    if (
                        word["display_bbox"][0] < bands[field][0] - 0.5
                        or word["display_bbox"][2] > bands[field][2] + 0.5
                    ):
                        ambiguous = True
                        continue
                    columns[field].append(word)
                values = {field: " ".join(word["text"] for word in columns[field]) for field in FIELDS}
                detail = {
                    "word_indices": [word["index"] for word in line],
                    "observed_fields": values,
                    "display_bboxes": [word["display_bbox"] for word in line],
                }
                if ambiguous:
                    refuse("ambiguous_column_assignment", **detail)
                    group = None
                    continue
                if values["document"]:
                    group = None
                    ordinal = 0
                    start, end = _date(values["service_start"]), _date(values["service_end"])
                    if (
                        start is None
                        or end is None
                        or start > end
                        or not DOCUMENT.fullmatch(values["document"])
                        or not values["payee"]
                        or not all(_date(values[field]) for field in ("date_posted", "service_start", "service_end"))
                    ):
                        refuse("incomplete_or_unsupported_group_header", **detail)
                        continue
                    group = {
                        "values": {field: values[field] for field in FIELDS[:5]},
                        "word_indices": {field: [word["index"] for word in columns[field]] for field in FIELDS[:5]},
                    }
                elif any(values[field] for field in FIELDS[1:5]):
                    refuse("unowned_metadata_or_summary", **detail)
                    group = None
                    continue
                amount = parse_amount(values["amount"])
                if group is None:
                    refuse("no_qualified_document_group", **detail)
                    continue
                if amount is None or not values["description"]:
                    refuse(
                        "unpriced_description_attachment_unqualified", document=group["values"]["document"], **detail
                    )
                    # A later priced line cannot cross an unqualified attachment.
                    group = None
                    continue
                if amount < 0:
                    refuse("negative_payment_not_qualified", **detail)
                    group = None
                    continue
                if any(label in values["description"].upper() for label in ("TOTAL", "BALANCE")):
                    refuse("summary_not_payment", **detail)
                    group = None
                    continue
                candidate = {
                    **group["values"],
                    "line_ordinal": ordinal,
                    "description": values["description"],
                    "amount": format(amount, ".2f"),
                    "office": context["office"],
                    "office_origin_page": page["source_page"],
                    "office_word_indices": office_spans[0],
                    **provenance,
                    "input_sha256": capture["input_sha256"],
                    "rule": RULE,
                    "status": "candidate",
                    "group_completion": "not_reconciled",
                    "header_cells_display": bands,
                    "field_word_indices": {
                        **group["word_indices"],
                        **{field: [word["index"] for word in columns[field]] for field in FIELDS[5:]},
                    },
                    "line_display_bboxes": detail["display_bboxes"],
                }
                result["candidates"].append(candidate)
                ordinal += 1
                if len(result["candidates"]) > MAX_CANDIDATES:
                    raise ValueError("Payment candidate count exceeds its bound")
            result["pages"].append(
                {
                    **provenance,
                    "status": "partial_candidates",
                    "candidates": len(result["candidates"]) - before,
                    "refusals": len(result["refusals"]) - page_refusals,
                }
            )
    result["selected_candidate_amount_sum"] = format(
        sum((Decimal(row["amount"]) for row in result["candidates"]), Decimal(0)), ".2f"
    )
    result["completion_status"] = "partial_not_reconciled"
    return result
