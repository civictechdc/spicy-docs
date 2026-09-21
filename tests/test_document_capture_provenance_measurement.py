"""The before/after receipt is checked from Git and the committed capture files."""

import copy
import hashlib
import json

import pytest

from tools.analysis.measure_document_capture_provenance import ROOT, git, inventory, measure

SIDECAR = ROOT / "docs/research/document-capture-provenance-2026-09-20.json"


def test_measurement_replays_the_pinned_commits():
    expected = json.loads(SIDECAR.read_bytes())
    result = measure(expected["beforeCommit"], expected["afterCommit"])
    expected.pop("retainedVerification", None)
    assert result == expected
    assert result["requests"] == 0
    assert result["captureCount"] == 7
    for row in result["families"]:
        # Historical receipts name historical bytes. Fresh converter runs may
        # update provenance; current source-field coverage is checked below.
        retained = git("show", f"{result['afterCommit']}:{row['path']}")
        assert hashlib.sha256(retained).hexdigest() == row["after"]["sha256"]


@pytest.mark.parametrize(
    "family",
    [
        "uslm-law",
        "bill-xml",
        "committee-report-html",
        "federal-register-xml",
        "cfr-reconstruction",
        "slip-opinion-pdf",
        "senate-expenditures-pdf",
    ],
)
def test_field_measurement_detects_removed_source_records(family):
    receipt = json.loads(SIDECAR.read_bytes())
    row = next(r for r in receipt["families"] if r["family"] == family)
    capture = json.loads((ROOT / row["path"]).read_bytes())
    observations = {
        r["observation"]["url"]: r["observation"]
        for r in json.loads((ROOT / receipt["observationInput"]["path"]).read_bytes())
    }
    assert inventory(capture, observations) == row["after"]["fields"]
    broken = copy.deepcopy(capture)
    broken["profile"]["ext"].pop("sourceRecords")
    measured = inventory(broken, observations)
    assert measured != row["after"]["fields"]
    assert measured["4.acquisitionRecord"] == {"present": 0, "total": 1}


def test_measurement_detects_missing_geometry_and_restored_zip_url():
    receipt = json.loads(SIDECAR.read_bytes())
    observations = {
        r["observation"]["url"]: r["observation"]
        for r in json.loads((ROOT / receipt["observationInput"]["path"]).read_bytes())
    }
    senate = next(r for r in receipt["families"] if r["family"] == "senate-expenditures-pdf")
    capture = json.loads((ROOT / senate["path"]).read_bytes())
    next(n for n in capture["nodes"] if n["kind"] == "page")["source"].pop("box")
    assert (
        inventory(capture, observations)["6.pageBox"]["present"]
        == senate["after"]["fields"]["6.pageBox"]["present"] - 1
    )
    law = next(r for r in receipt["families"] if r["family"] == "uslm-law")
    capture = json.loads((ROOT / law["path"]).read_bytes())
    archive = capture["profile"]["ext"].pop("archiveMember")["archive"]
    capture["artifact"]["locator"]["url"] = archive["url"]
    assert inventory(capture, observations)["3.publisherUrl"] == {"present": 0, "total": 1}
