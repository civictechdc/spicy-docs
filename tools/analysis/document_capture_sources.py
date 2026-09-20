"""Offline source-record mapping for the bounded worked captures.

Read independently retained observations, never a previous capture's values.
Unknown retrieval precision and missing MODS stay missing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from spicy_docs.sources.govinfo.mods import parse_govinfo_mods

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"


def source_records(digest: str) -> list[dict[str, Any]]:
    rows = json.loads((FIXTURES / "document_capture_provenance/observations.json").read_bytes())
    return [
        {"role": "acquisition", **row["observation"], "receipt": row["receipt"]}
        for row in rows
        if row["observation"]["sha256"] == digest
    ]


def mods_record(path: Path, package: str, granule: str | None) -> dict[str, Any]:
    data = path.read_bytes()
    parsed = parse_govinfo_mods(data)
    record = parsed.package
    scope = next((r for r in record.related_items if r.element.attribute("type") == "host"), record)
    package_ids = [n.text for n in scope.fields("extension", "accessId")]
    granule_ids = [n.text for n in record.fields("extension", "accessId")] if granule else []
    if package not in package_ids or (granule is not None and granule not in granule_ids):
        raise ValueError("MODS does not state the selected package/granule pair")
    digest = hashlib.sha256(data).hexdigest()
    observed = source_records(digest)
    # Preserve the publisher's spelling and XML path, not normalized joins.
    inventory_names = {
        "identifier",
        "recordIdentifier",
        "accessId",
        "dateIssued",
        "dateIngested",
        "recordCreationDate",
        "recordChangeDate",
        "action",
        "bill",
        "law",
        "congCommittee",
        "congress",
        "chamber",
        "session",
        "title",
    }
    fields = []
    pending = [record.element]
    while pending:
        element = pending.pop()
        name = element.name.rsplit("}", 1)[-1]
        if name in inventory_names:
            fields.append(
                {
                    "name": name,
                    "value": element.text,
                    "attributes": dict(element.attributes),
                    "path": list(element.path),
                }
            )
        pending.extend(reversed(element.children))
    return {
        "role": "mods",
        "path": str(path.relative_to(ROOT)),
        "sha256": digest,
        "byteSize": len(data),
        "mediaType": "application/xml",
        "packageId": package,
        "granuleId": granule,
        "sourceFields": fields,
        "identityPaths": ["mods/extension/accessId", "mods/relatedItem[@type='host']/extension/accessId"]
        if granule
        else ["mods/extension/accessId"],
        **({k: v for k, v in observed[0].items() if k not in {"role", "mediaType"}} if observed else {}),
    }


def populate(conversion: Any) -> None:
    """Populate only byte-bound observations; repeated calls replace the same fields."""
    artifact, ext = conversion.artifact, conversion.profile_ext
    member = ext.get("archiveMember")
    source = member["archive"] if member else ext.get("derivedFrom", artifact)
    records = source_records(source["sha256"])
    for record in records:
        if any(source[k] != record[k] for k in ("sha256", "byteSize", "mediaType")):
            raise ValueError("retained source record differs from the artifact")
        # A derived cut is not retrieved: its publisher source owns the timestamp.
        if "derivedFrom" not in ext:
            artifact["retrievedAt"] = record["retrievedAt"]
        if not member and "derivedFrom" not in ext:
            artifact["locator"]["url"] = record["url"]
    identity = None
    if artifact["locator"].get("publisher") == "GovInfo" or conversion.family == "senate-expenditures-pdf":
        url = source.get("url") or source.get("locator", {}).get("url", "")
        parts = urlsplit(url).path.split("/")
        if "pkg" in parts:
            package = parts[parts.index("pkg") + 1]
            file_id = parts[-1].rsplit(".", 1)[0]
            identity = {
                "packageId": package,
                "granuleId": file_id if file_id != package else None,
                "basis": "retained content/pkg URL; null means package-level rendition",
            }
        elif member:
            identity = {
                "packageId": artifact["locator"]["publisherId"],
                "granuleId": None,
                "basis": "retained PLAW member name and validated USLM identity; package-level rendition",
            }
        elif ext.get("packageId"):
            package = ext["packageId"]
            file_id = ext["fileName"].removesuffix(".pdf")
            identity = {
                "packageId": package,
                "granuleId": file_id if file_id != package else None,
                "basis": "caller-selected package and file; acquisition and MODS remain unverified",
            }
    if identity:
        package, granule = identity["packageId"], identity["granuleId"]
        mods = {
            "CRPT-119hrpt1": FIXTURES / "govinfo_bodies/mods-CRPT-119hrpt1.xml",
            "GPO-CDOC-119sdoc3": FIXTURES / "document_capture_provenance/mods-GPO-CDOC-119sdoc3-1.xml",
        }.get(package)
        if mods:
            records.append(mods_record(mods, package, granule))
            identity["basis"] = "pinned MODS accessId; host accessId for the package when granule-scoped"
        ext["govinfoIdentity"] = identity
    ext["sourceRecords"] = records
    ext["renditionReason"] = "Explicit retained sample selection; no fallback attempted. " + (
        "Read PDF through the pinned extractor intermediate." if conversion.intermediate else "Read publisher markup."
    )
