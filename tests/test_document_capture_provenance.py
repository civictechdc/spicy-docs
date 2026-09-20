"""Provenance checks read committed captures, independently of conversion."""

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from spicy_docs.schemas.document_capture.provenance import (
    FAMILY_REQUIREMENTS,
    check_archive_member,
    check_artifact_binding,
    check_provenance,
)

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


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.stem)
def test_committed_provenance_has_only_the_documented_evidence_gaps(path):
    from collections import Counter

    capture = json.loads(path.read_bytes())
    expected = {
        "uslm-law": {"mods-record": 1},
        "bill-xml": {"mods-record": 1},
        "committee-report-html": {"retrieval-timestamp": 1},
        "cfr-reconstruction": {"retrieval-timestamp": 1, "mods-record": 1},
        "federal-register-xml": {},
        "slip-opinion-pdf": {},
        "senate-expenditures-pdf": {"coordinate-fields": 6},
    }
    assert Counter(f["code"] for f in check_provenance(capture)) == expected[capture["profile"]["name"]]


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.stem)
def test_required_family_provenance_omissions_are_findings(path):
    capture = json.loads(path.read_bytes())
    family = capture["profile"]["name"]
    ext = capture["profile"]["ext"]
    source = ext.get("archiveMember", {}).get("archive") or ext.get("derivedFrom") or capture["artifact"]
    source.pop("retrievedAt", None)
    source.pop("url", None)
    source.get("locator", {}).pop("url", None)
    ext.pop("sourceRecords", None)
    ext.pop("govinfoIdentity", None)
    ext.pop("renditionReason", None)
    ext.pop("pageSizes", None)
    capture["rendition"].pop("intermediate", None)
    capture["nodes"][0]["derivation"] = "reconstructed"
    for span in capture["evidence"]:
        for key in ("box", "start", "path"):
            span.get("source", {}).pop(key, None)
    for n in capture["nodes"]:
        n.pop("decision", None)
        n.pop("pageSize", None)
        for key in ("box", "start", "path"):
            n.get("source", {}).pop(key, None)
    found = {f["code"] for f in check_provenance(capture)}
    expected = set(FAMILY_REQUIREMENTS[family])
    assert expected <= found


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.stem)
def test_full_precision_and_mods_values_are_bound_to_independent_records(path):
    from tools.analysis.document_capture_sources import mods_record

    capture = json.loads(path.read_bytes())
    ext = capture["profile"]["ext"]
    source = ext.get("archiveMember", {}).get("archive") or ext.get("derivedFrom") or capture["artifact"]
    source_url = source.get("url") or source.get("locator", {}).get("url")
    assert source["retrievedAt"] == OBSERVATIONS[source_url]["retrievedAt"]
    for r in ext["sourceRecords"]:
        if r["role"] == "mods":
            assert r == mods_record(ROOT / r["path"], r["packageId"], r["granuleId"])
    if "derivedFrom" in ext:
        assert capture["artifact"].get("retrievedAt") is None
        assert "url" not in capture["artifact"]["locator"]
        assert source["sha256"] != capture["artifact"]["sha256"]


def test_date_only_invalid_dates_and_geometry_are_findings():
    from spicy_docs.schemas.document_capture.provenance import coordinate_fields_present, full_timestamp

    assert full_timestamp("2026-09-20T12:34:56.123456Z")
    for invalid in ("2026-09-20", "2026-02-30T12:34:56Z", "2026-09-20T12:34:56", "2026-09-20T12:34Z"):
        assert not full_timestamp(invalid)
    assert coordinate_fields_present({"coordinateSystem": "page-region", "page": 1, "box": [0, 0, 1000, 1000]})
    for broken in ({"page": 1}, {"box": [0, 0, 1, 1]}, {"page": 1, "box": [2, 2, 1, 1]}):
        assert not coordinate_fields_present({"coordinateSystem": "page-region", **broken})


def test_fresh_converters_populate_precise_receipts_mods_and_decisions():
    from tools.analysis import document_capture as dc

    bill = dc.convert_bill(dc.FIXTURES / "govinfo_bills/text-119hjres25enr.xml").capture()
    assert bill["artifact"]["retrievedAt"] == "2026-09-12T12:29:18.332855+00:00"
    report = dc.convert_committee_report(dc.FIXTURES / "govinfo_bodies/body-CRPT-119hrpt1.htm").capture()
    assert [f["code"] for f in check_provenance(report)] == ["retrieval-timestamp"]
    assert report["profile"]["ext"]["govinfoIdentity"]["granuleId"] is None
