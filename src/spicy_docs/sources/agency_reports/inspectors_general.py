"""Read retained unitedstates/inspectors-general report metadata without fetching files.

The unitedstates/reports archive uses this format. Archive paths, report years,
and publication dates are independent observations; none is rewritten from another.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from spicy_docs.reading.json_input import load_bounded_json


class InspectorGeneralReportError(ValueError):
    """The retained input is not supported inspector-general report metadata."""


def _link(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InspectorGeneralReportError(f"Expected a URL in {field}")
    try:
        target = urlsplit(value)
        valid = target.scheme in {"http", "https"} and bool(target.hostname)
        valid = valid and not target.username and not target.password
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in value):
        raise InspectorGeneralReportError(f"Expected an absolute HTTP URL in {field}")
    return value


def parse_inspector_general_report(
    body: bytes,
    *,
    url: str,
    max_bytes: int = 1_000_000,
    max_nodes: int = 100_000,
    max_depth: int = 64,
) -> dict:
    """Return the complete source record and its declared links from retained JSON.

    ``url`` identifies these metadata bytes, preferably at a pinned archive commit.
    ``assets`` describes source-declared originals; it does not prove that an
    original exists in an archive or has been acquired. Use a retained archive
    listing to select archived files. Unknown fields and literal values survive.
    """
    _link(url, "metadata locator")
    record = load_bounded_json(
        body,
        source="inspector-general report",
        error_type=InspectorGeneralReportError,
        number_policy="finite-float",
        max_bytes=max_bytes,
        max_nodes=max_nodes,
        max_depth=max_depth,
    )
    if not isinstance(record, dict):
        raise InspectorGeneralReportError("Report metadata must be a JSON object")
    for field in ("report_id", "inspector", "agency", "agency_name", "title", "published_on", "type"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise InspectorGeneralReportError(f"Missing report field: {field}")
    if type(record.get("year")) is not int:
        raise InspectorGeneralReportError("Report year must be an integer")
    if "unreleased" in record and type(record["unreleased"]) is not bool:
        raise InspectorGeneralReportError("Report unreleased must be a boolean")

    assets = []
    if record.get("url") is not None:
        original = _link(record["url"], "url")
        if not isinstance(record.get("file_type"), str) or not record["file_type"].strip():
            raise InspectorGeneralReportError("Report URL requires file_type")
        assets.append({"url": original, "file_type": record["file_type"], "source_field": "url"})
    elif record.get("unreleased") is not True or not record.get("landing_url"):
        raise InspectorGeneralReportError("Report needs a URL or unreleased=true with landing_url")
    links = [
        {"url": _link(record[field], field), "source_field": field}
        for field in ("inspector_url", "landing_url", "summary_url")
        if record.get(field) is not None
    ]
    return {
        "source": {"url": url, "sha256": "sha256:" + hashlib.sha256(body).hexdigest(), "bytes": len(body)},
        "record": record,
        "assets": assets,
        "links": links,
    }
