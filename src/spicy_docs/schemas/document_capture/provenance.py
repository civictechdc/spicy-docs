"""SpicyDocs provenance checks, additional to the unchanged Rulespec schema.

No acquisition or implicit file access. Callers supply retained bytes and
independent URL observations; missing evidence is a finding, never a pass.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable, Mapping
from typing import Any


def check_artifact_binding(
    artifact: Mapping[str, Any],
    *,
    read_bytes: Callable[[str], bytes],
    observations: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Check every stated path and URL against independent retained evidence.

    Observations map the exact URL to sha256, byteSize and mediaType. A local
    file matching the digest cannot establish that a different URL names it.
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
