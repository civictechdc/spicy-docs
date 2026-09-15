"""Read retained native NIEM FOIA annual reports; no fetching or statistical interpretation."""

from __future__ import annotations

import hashlib

from spicy_docs.reading.xml import scan_xml

_EXCHANGE = "http://leisp.usdoj.gov/niem/FoiaAnnualReport/exchange/"
_EXTENSION = "http://leisp.usdoj.gov/niem/FoiaAnnualReport/extension/"
_CORE = "{http://niem.gov/niem/niem-core/2.0}"
_STRUCTURES = "{http://niem.gov/niem/structures/2.0}"
_WORD = "{http://schemas.microsoft.com/office/2006/xmlPackage}package"


class FoiaReportError(ValueError):
    """The bytes cannot be read as a supported native FOIA annual report."""


def parse_foia_annual_report(body: bytes, *, max_bytes: int = 4 * 1024**2, max_elements: int = 100_000) -> dict:
    """Preserve every XML element, association, namespace declaration and literal value.

    Supports the NIEM exchange 1.02/1.03 roots observed in retained reports.
    ``child_indices`` count element children from zero; root is []. They are
    tree positions, not byte offsets. Prefix declarations retain QName context;
    comments, processing instructions and lexical spelling remain in source bytes.
    Values are not coerced to numbers, deduplicated, summed or XSD-validated.
    Word Flat OPC is refused as a different document representation.
    """
    if type(max_elements) is not int or max_elements <= 0:
        raise FoiaReportError("max_elements must be a positive integer")
    rows: list[dict] = []
    stack: list[dict] = []
    declarations: dict[str, str] = {}
    version = ""

    def start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal version
        if len(rows) >= max_elements:
            raise FoiaReportError("FOIA annual report exceeds max_elements")
        parent = stack[-1] if stack else None
        if parent is None:
            if tag == _WORD:
                raise FoiaReportError("Word Flat OPC is not native FOIA data; retain it for document processing")
            version = next((v for v in ("1.02", "1.03") if tag == f"{{{_EXCHANGE}{v}}}FoiaAnnualReport"), "")
            if not version:
                raise FoiaReportError("FOIA annual report has an unsupported root or namespace")
        path = [] if parent is None else [*rows[parent["index"]]["child_indices"], parent["children"]]
        if parent is not None:
            parent["children"] += 1
        index = len(rows)
        rows.append(
            {
                "child_indices": path,
                "parent": None if parent is None else parent["index"],
                "tag": tag,
                "attributes": attributes,
                "namespace_declarations": dict(declarations),
                "text": [],
                "tail": [],
            }
        )
        declarations.clear()
        stack.append({"index": index, "children": 0, "last_child": None})

    def end(_tag: str) -> None:
        frame = stack.pop()
        if stack:
            stack[-1]["last_child"] = frame["index"]

    def data(text: str) -> None:
        if stack:
            frame = stack[-1]
            child = frame["last_child"]
            rows[frame["index"] if child is None else child]["text" if child is None else "tail"].append(text)

    scan_xml(
        body,
        start=start,
        end=end,
        data=data,
        namespace=declarations.__setitem__,
        max_bytes=max_bytes,
        max_depth=64,
        error_type=FoiaReportError,
        label="FOIA annual report",
    )
    children: dict[int | None, list[int]] = {}
    for index, row in enumerate(rows):
        for key in ("text", "tail"):
            row[key] = "".join(row[key]) if row[key] else None
        children.setdefault(row["parent"], []).append(index)

    def fields(parent: int, name: str) -> list[dict]:
        return [{"element": i, "value": rows[i]["text"]} for i in children.get(parent, []) if rows[i]["tag"] == name]

    # NIEM 1.02 uses DocumentFiscalYear; 1.03 renamed it DocumentFiscalYearDate.
    year_field = "DocumentFiscalYear" if version == "1.02" else "DocumentFiscalYearDate"
    years = fields(0, f"{{{_EXTENSION}{version}}}{year_field}")
    if len(years) != 1 or (not years[0]["value"] or not years[0]["value"].strip()) or children.get(years[0]["element"]):
        raise FoiaReportError("FOIA annual report needs one nonempty native fiscal year")
    organizations = [
        {
            "element": i,
            "id": rows[i]["attributes"].get(_STRUCTURES + "id"),
            "names": fields(i, _CORE + "OrganizationName"),
            "abbreviations": fields(i, _CORE + "OrganizationAbbreviationText"),
        }
        for i in children.get(0, [])
        if rows[i]["tag"] == _CORE + "Organization"
    ]
    if not organizations:
        raise FoiaReportError("FOIA annual report lacks its native organization")
    return {
        "source": {"sha256": "sha256:" + hashlib.sha256(body).hexdigest(), "bytes": len(body)},
        "metadata": {
            "schema_version": version,
            "fiscal_year": years[0],
            "organizations": organizations,
            "creation_dates": [
                value
                for i in children.get(0, [])
                if rows[i]["tag"] == _CORE + "DocumentCreationDate"
                for value in fields(i, _CORE + "Date")
            ],
        },
        "elements": rows,
    }
