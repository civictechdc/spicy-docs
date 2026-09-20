"""Provenance checks read committed captures, independently of conversion."""

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from spicy_docs.schemas.document_capture.provenance import check_archive_member, check_artifact_binding

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/document_capture_provenance"
CAPTURES = sorted((ROOT / "docs/research/document-capture-schema-2026-09-19").glob("*.capture.json")) + [
    ROOT / "tests/fixtures/document_capture_pdf_tables/senate-page17.capture.json"
]
OBSERVATIONS = {
    r["observation"]["url"]: r["observation"] for r in json.loads((FIXTURE / "observations.json").read_bytes())
}


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.stem)
def test_every_stated_artifact_locator_names_its_digest(path):
    capture = json.loads(path.read_bytes())
    assert (
        check_artifact_binding(
            capture["artifact"], read_bytes=lambda p: (ROOT / p).read_bytes(), observations=OBSERVATIONS
        )
        == []
    )


def test_public_law_cannot_pair_archive_url_with_member_digest():
    capture = json.loads(next(p for p in CAPTURES if p.name.startswith("plaw-")).read_bytes())
    member = capture["profile"]["ext"]["archiveMember"]
    retained = json.loads((FIXTURE / "public-law.json").read_bytes())["archiveMember"]
    assert member == retained
    assert all(capture["artifact"][k] == member[k] for k in ("sha256", "byteSize", "mediaType"))
    capture["artifact"]["locator"]["url"] = member["archive"]["url"]
    assert check_artifact_binding(
        capture["artifact"], read_bytes=lambda p: (ROOT / p).read_bytes(), observations=OBSERVATIONS
    ) == ["artifact-url-bytes-mismatch"]


def test_archive_member_check_reads_both_objects_and_refuses_mutations():
    data = b"<law>retained bytes</law>"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("laws/one.xml", data)
    archive = stream.getvalue()
    artifact = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "byteSize": len(data),
        "mediaType": "application/xml",
        "locator": {"path": "one.xml"},
    }
    member = {
        **{k: artifact[k] for k in ("sha256", "byteSize", "mediaType")},
        "memberPath": "laws/one.xml",
        "archive": {
            "url": "https://example.test/laws.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
            "byteSize": len(archive),
            "mediaType": "application/zip",
        },
    }
    capture = {"artifact": artifact, "profile": {"ext": {"archiveMember": member}}}
    assert check_archive_member(capture, archive) == []
    assert check_archive_member(capture, archive + b"x") == ["archive-bytes-mismatch"]
    broken = copy.deepcopy(capture)
    broken["profile"]["ext"]["archiveMember"]["memberPath"] = "wrong.xml"
    assert check_archive_member(broken, archive) == ["archive-member-not-unique"]
    broken = copy.deepcopy(capture)
    broken["artifact"]["sha256"] = "0" * 64
    assert check_archive_member(broken, archive) == ["archive-member-bytes-mismatch"]


def test_generic_binding_check_does_not_trust_a_matching_local_file():
    data = b"same local file"
    artifact = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "byteSize": len(data),
        "mediaType": "text/plain",
        "locator": {"path": "file.txt", "url": "https://example.test/wrong"},
    }
    observed = {artifact["locator"]["url"]: {"sha256": "0" * 64, "byteSize": len(data), "mediaType": "text/plain"}}
    assert check_artifact_binding(artifact, read_bytes=lambda _: data, observations=observed) == [
        "artifact-url-bytes-mismatch"
    ]
    assert check_artifact_binding(artifact, read_bytes=lambda _: data, observations={}) == ["artifact-url-unverified"]
