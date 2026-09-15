"""Literal official filing field definitions, selected explicitly by the caller."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict, dict]:
    data = json.loads(files(__package__).joinpath("field_layouts.json").read_bytes())
    index: dict[tuple, list] = {}
    for layout in data["layouts"]:
        index.setdefault((layout["family"], layout["version"], layout["form"]), []).append(layout)
    return data, index


def filing_layouts() -> list[dict]:
    """List exact dictionary selectors, including ambiguous source rows.

    Versions and form names are dictionary spelling, not inferred matches for
    native filing headers or record types. Listing a sheet does not establish
    that the publisher accepts that record type in new filings.
    """
    data, _ = _catalog()
    return [{k: x[k] for k in ("family", "version", "form", "row")} for x in data["layouts"]]


def filing_layout(*, family: str, version: str, form: str, row: int | None = None) -> dict:
    """Return one pinned dictionary layout, with literal labels and source cells.

    Exact selection only: no version rounding, suffix stripping or prefix routing.
    If the dictionary repeats a version/form, select its source row explicitly.
    Returned data is independent of the cached definitions and safe to modify.
    """
    if row is not None and (type(row) is not int or row <= 0):
        raise ValueError("row must be a positive source row number")
    data, index = _catalog()
    choices = index.get((family, version, form), [])
    if row is not None:
        choices = [x for x in choices if x["row"] == row]
    if not choices:
        raise KeyError((family, version, form, row))
    if len(choices) != 1:
        raise ValueError("FEC dictionary has multiple layouts; select an explicit source row")
    result = copy.deepcopy(choices[0])
    result["source"] = copy.deepcopy(data["sources"][result.pop("source_index")])
    return result


def map_filing_fields(record: dict, *, layout: dict, format_version: str, max_fields: int = 10_000) -> dict:
    """Annotate a positional filing record without moving or dropping its values.

    Pass a layout from ``filing_layout`` and the original header's format_version.
    Selection is caller-supplied, not a compatibility or conformance verdict.
    Every observed position survives; absent trailing fields differ from blanks,
    and separated bodies remain references. Duplicate labels are not dictionary
    keys. No original is reopened, and no amounts or codes are coerced.
    """
    if type(max_fields) is not int or max_fields <= 0:
        raise ValueError("max_fields must be a positive integer")
    if not isinstance(format_version, str) or not format_version:
        raise ValueError("format_version must retain the nonempty native header value")
    if {"declared_format_version", "field_mapping"} & record.keys():
        raise ValueError("Filing record already contains mapping output members")
    count = record.get("field_count")
    definitions = layout["fields"]
    if (
        record.get("kind") != "record"
        or type(count) is not int
        or count < 0
        or max(count, len(definitions)) > max_fields
    ):
        raise ValueError("Expected a positional filing record and layout within max_fields")
    values = record["fields"]
    bodies = record.get("embedded_bodies", [])
    if not isinstance(values, dict) or not isinstance(bodies, list) or len(values) + len(bodies) != count:
        raise ValueError("Filing values and body references must account for each position exactly once")
    body_indices = [b["field_index"] for b in bodies]
    if (
        any(type(i) is not int or not 0 <= i < count for i in body_indices)
        or len(set(body_indices)) != len(body_indices)
        or set(values) & {str(i) for i in body_indices}
        or set(values) | {str(i) for i in body_indices} != {str(i) for i in range(count)}
    ):
        raise ValueError("Filing values and body references must account for each position exactly once")
    body_indices = set(body_indices)
    annotations = [
        {
            "index": i,
            "presence": "absent" if i >= count else "body" if i in body_indices else "value",
            "definition": {k: definitions[i][k] for k in ("label", "cell")} if i < len(definitions) else None,
        }
        for i in range(max(count, len(definitions)))
    ]
    reference = {k: copy.deepcopy(v) for k, v in layout.items() if k not in {"fields", "notes", "source"}}
    reference["source"] = {k: copy.deepcopy(v) for k, v in layout["source"].items() if k != "notes"}
    return {
        **copy.deepcopy(record),
        "declared_format_version": format_version,
        "field_mapping": {
            "selection": "caller-selected",
            "layout": reference,
            "width": "extra_fields" if count > len(definitions) else "short" if count < len(definitions) else "equal",
            "annotations": annotations,
        },
    }
