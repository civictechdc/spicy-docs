"""SpicyDocs provenance checks, additional to the unchanged Rulespec schema.

No acquisition or implicit file access. Callers supply retained bytes and
independent URL observations; missing evidence is a finding, never a pass.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Mapping
from typing import Any

GOVINFO_FAMILIES = frozenset(
    {"uslm-law", "bill-xml", "committee-report-html", "cfr-reconstruction", "senate-expenditures-pdf"}
)
PDF_FAMILIES = frozenset({"cfr-reconstruction", "slip-opinion-pdf", "senate-expenditures-pdf"})
COMMON_REQUIREMENTS = (
    "publisher-url",
    "retrieval-timestamp",
    "acquisition-record",
    "rendition-reason",
    "coordinate-fields",
    "derived-node-decision",
)
FAMILY_REQUIREMENTS = {
    family: COMMON_REQUIREMENTS
    + (("govinfo-pair", "mods-record") if family in GOVINFO_FAMILIES else ())
    + (("pdf-intermediate", "page-dimensions") if family in PDF_FAMILIES else ())
    for family in GOVINFO_FAMILIES | {"federal-register-xml", "slip-opinion-pdf"}
}


def full_timestamp(value: Any) -> bool:
    """Require seconds and a timezone, retaining any recorded fractional precision."""
    from datetime import datetime

    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def coordinate_fields_present(source: Mapping[str, Any]) -> bool:
    """Check stated coordinates, without manufacturing geometry for unknown regions."""
    system = source.get("coordinateSystem")
    if system == "none":
        return True
    if system == "xml-node-path":
        return bool(source.get("path"))
    if system == "utf8-byte":
        return (
            isinstance(source.get("start"), int)
            and isinstance(source.get("end"), int)
            and 0 <= source["start"] <= source["end"]
        )
    if system == "page-region":
        box = source.get("box", [])
        return (
            type(source.get("page")) is int
            and source["page"] > 0
            and len(box) == 4
            and all(type(v) is int and 0 <= v <= 1000 for v in box)
            and box[0] <= box[2]
            and box[1] <= box[3]
        )
    return False


def decision_required(node: Mapping[str, Any]) -> bool:
    """Whether this node must carry a recorded decision: a reconstructed/markup/pdf-text/ocr derivation, no
    coordinate system, or a level heading with no SOURCE attribute."""
    return (
        node.get("derivation") in {"reconstructed", "markup", "pdf-text", "ocr"}
        or (node.get("source", {}).get("coordinateSystem", "none") == "none")
        or (
            node.get("kind") == "heading"
            and "level" in node
            and not node.get("source", {}).get("attributes", {}).get("SOURCE")
        )
    )


def check_provenance(capture: Mapping[str, Any]) -> list[dict[str, str]]:
    """Report the per-family provenance omissions the parent schema accepts, as ``{"code", "path"}`` findings.

    Run parent/profile validation too; these are SpicyDocs' stricter family admission checks, and an issue explaining
    missing evidence never counts as supplying it.
    """
    findings = []

    def need(ok: Any, code: str, path: str) -> None:
        if not ok:
            findings.append({"code": code, "path": path})

    family = capture.get("profile", {}).get("name")
    if family not in FAMILY_REQUIREMENTS:
        return [{"code": "unknown-provenance-family", "path": "/profile/name"}]
    artifact = capture.get("artifact", {})
    ext = capture["profile"].get("ext", {})
    source = ext.get("archiveMember", {}).get("archive") or ext.get("derivedFrom") or artifact
    url = source.get("url") or source.get("locator", {}).get("url")
    need(isinstance(url, str) and url.startswith(("https://", "http://")), "publisher-url", "/artifact/locator/url")
    need(full_timestamp(source.get("retrievedAt")), "retrieval-timestamp", "/artifact/retrievedAt")
    records = ext.get("sourceRecords", [])
    acquisition = [r for r in records if r.get("role") == "acquisition"]
    need(
        any(
            r.get("sha256") == source.get("sha256")
            and r.get("receipt", {}).get("sha256")
            and r.get("receipt", {}).get("path")
            for r in acquisition
        ),
        "acquisition-record",
        "/profile/ext/sourceRecords",
    )
    for index, record in enumerate(acquisition):
        need(
            all(record.get(k) == source.get(k) for k in ("sha256", "byteSize", "mediaType", "retrievedAt"))
            and record.get("url") == url,
            "acquisition-record-mismatch",
            f"/profile/ext/sourceRecords/{index}",
        )
    need(ext.get("renditionReason"), "rendition-reason", "/profile/ext/renditionReason")
    if family in GOVINFO_FAMILIES:
        identity = ext.get("govinfoIdentity", {})
        need(
            identity.get("packageId") and "granuleId" in identity and identity.get("basis"),
            "govinfo-pair",
            "/profile/ext/govinfoIdentity",
        )
        mods = [r for r in records if r.get("role") == "mods"]
        need(
            any(
                r.get("path")
                and r.get("sha256")
                and r.get("identityPaths")
                and r.get("packageId") == identity.get("packageId")
                and "granuleId" in r
                and r["granuleId"] == identity.get("granuleId")
                for r in mods
            ),
            "mods-record",
            "/profile/ext/sourceRecords",
        )
    if family in PDF_FAMILIES:
        intermediate = capture.get("rendition", {}).get("intermediate", {})
        need(
            intermediate.get("sha256") and intermediate.get("producer") and intermediate.get("locator"),
            "pdf-intermediate",
            "/rendition/intermediate",
        )
    defaults = capture.get("rendition", {}).get("spanDefaults", {})
    pages = set()
    for i, span in enumerate(capture.get("evidence", [])):
        source = {**defaults, **span.get("source", {})}
        if source.get("page") is not None:
            pages.add(source["page"])
        need(
            coordinate_fields_present({**defaults, **span.get("source", {})}),
            "coordinate-fields",
            f"/evidence/{i}/source",
        )
    for i, node in enumerate(capture.get("nodes", [])):
        if node.get("source", {}).get("page") is not None:
            pages.add(node["source"]["page"])
        need(coordinate_fields_present(node.get("source", {})), "coordinate-fields", f"/nodes/{i}/source")
        if decision_required(node):
            decision = node.get("decision", {})
            need(
                decision.get("method") in {"rule", "model", "generated"} and decision.get("rule"),
                "derived-node-decision",
                f"/nodes/{i}/decision",
            )
    sizes = {s["page"]: s for s in ext.get("pageSizes", [])}
    sizes.update(
        {
            n.get("source", {}).get("page"): n.get("pageSize", {})
            for n in capture.get("nodes", [])
            if n.get("kind") == "page"
        }
    )
    for page in sorted(pages):
        size = sizes.get(page, {})
        need(
            size.get("unit") == "point" and size.get("width", 0) > 0 and size.get("height", 0) > 0,
            "page-dimensions",
            f"/page/{page}",
        )
    return findings


def check_artifact_binding(
    artifact: Mapping[str, Any],
    *,
    read_bytes: Callable[[str], bytes],
    observations: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Check every stated path and URL against independent retained evidence: path bytes against the digest and size,
    URL against caller-supplied observations.

    Observations map the exact URL to sha256, byteSize and mediaType, because a local file matching the digest cannot
    establish that a different URL names it.
    """
    findings = []
    locator = artifact.get("locator", {})
    if not (locator.get("path") or locator.get("url")):
        findings.append("artifact-locator-missing")
    if path := locator.get("path"):
        data = read_bytes(path)
        if hashlib.sha256(data).hexdigest() != artifact.get("sha256") or len(data) != artifact.get("byteSize"):
            findings.append("artifact-path-bytes-mismatch")
    if url := locator.get("url"):
        observed = observations.get(url)
        if observed is None:
            findings.append("artifact-url-unverified")
        elif any(artifact.get(k) != observed.get(k) for k in ("sha256", "byteSize", "mediaType")):
            findings.append("artifact-url-bytes-mismatch")
    return findings


def check_archive_member(capture: Mapping[str, Any], archive_bytes: bytes) -> list[str]:
    """Prove the archive pin and the exact, uniquely named uncompressed member."""
    member = capture.get("profile", {}).get("ext", {}).get("archiveMember")
    if not member:
        return ["archive-member-missing"]
    archive = member["archive"]
    if (
        hashlib.sha256(archive_bytes).hexdigest() != archive["sha256"]
        or len(archive_bytes) != archive["byteSize"]
        or archive["mediaType"] != "application/zip"
    ):
        return ["archive-bytes-mismatch"]
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
        matches = [i for i in z.infolist() if i.filename == member["memberPath"]]
        if len(matches) != 1:
            return ["archive-member-not-unique"]
        data = z.read(matches[0])
    artifact = capture["artifact"]
    if (
        hashlib.sha256(data).hexdigest() != member["sha256"]
        or len(data) != member["byteSize"]
        or any(member[k] != artifact[k] for k in ("sha256", "byteSize", "mediaType"))
        or artifact["locator"].get("url") == archive["url"]
    ):
        return ["archive-member-bytes-mismatch"]
    return []
