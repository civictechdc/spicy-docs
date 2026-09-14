"""The runnable USLM capture example retains exact bytes and truthful failure evidence."""

import hashlib
import io
import json
import socket
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from examples import uslm_capture
from spicy_docs.sources.govinfo.uslm import PublicLawSelection, StatuteCompilationSelection, UslmSourceError
from spicy_docs.sources.govinfo.uslm_acquisition import UslmAcquisitionBudget, UslmSourceUnavailableError

FIXTURES = Path(__file__).parent / "fixtures" / "uslm"
LAW_XML = (FIXTURES / "plaw-119publ1.xml").read_bytes()
COMPS_XML = (FIXTURES / "comps-10542.xml").read_bytes()
BUDGET = UslmAcquisitionBudget(2, 65536, 7, 0)
NOW = datetime(2026, 9, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("capture example qualification must remain offline")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def transport_for(body, *, status=200, media_type="application/xml"):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": media_type})

    return httpx.MockTransport(handle), calls


def archive(*members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


LAW = PublicLawSelection(119, "public", 1)


def capture(output, transport, *, route="public-law", selection=LAW):
    return uslm_capture.run_capture(
        output, route=route, selection=selection, budget=BUDGET, transport=transport, clock=lambda: NOW
    )


def test_law_capture_writes_exact_bytes_metadata_and_receipt(tmp_path):
    transport, calls = transport_for(LAW_XML, media_type="text/xml; charset=UTF-8")
    output = tmp_path / "law"
    receipt = capture(output, transport)
    assert (output / "response.xml").read_bytes() == LAW_XML
    written = json.loads((output / "receipt.json").read_text())
    assert written == json.loads(json.dumps(receipt))
    assert receipt["outcome"] == "captured" and receipt["requestCount"] == len(calls) == 1
    assert receipt["selection"] == {"congress": 119, "kind": "public", "number": 1}
    assert receipt["capture"]["file"] == "response.xml"
    assert receipt["capture"]["sha256"] == "sha256:" + hashlib.sha256(LAW_XML).hexdigest()
    assert receipt["capture"]["observedAt"] == "2026-09-14T00:00:00Z"
    assert written["source"]["metadata"]["citable_as"] == ["Public Law 119–1", "139 Stat. 3"]
    assert receipt["producer"]["package"] == "spicy-docs"


def test_archive_capture_lists_every_validated_entry(tmp_path):
    body = archive(("COMPS-10542.xml", COMPS_XML))
    transport, _calls = transport_for(body, media_type="application/zip")
    output = tmp_path / "comps"
    receipt = capture(output, transport, route="statute-compilations-archive", selection=None)
    assert (output / "response.zip").read_bytes() == body
    entries = json.loads((output / "entries.json").read_text())
    assert [entry["name"] for entry in entries] == ["COMPS-10542.xml"]
    assert entries[0]["metadata"]["file_id"] == "10542"
    assert entries[0]["metadata"]["current_through_public_law"] == ["113–23"]
    assert receipt["source"]["archive"] == {
        "source": "statute-compilation",
        "entryCount": 1,
        "file": "entries.json",
        "sha256": "sha256:" + hashlib.sha256((output / "entries.json").read_bytes()).hexdigest(),
        "byteSize": (output / "entries.json").stat().st_size,
    }
    assert receipt["selection"] is None


def test_public_law_archive_selection_is_recorded(tmp_path):
    transport, _calls = transport_for(archive(("PLAW-119publ1.xml", LAW_XML)), media_type="application/zip")
    receipt = capture(tmp_path / "laws", transport, route="public-law-archive", selection=(119, "public"))
    assert receipt["selection"] == {"congress": 119, "kind": "public"}
    assert receipt["capture"]["requestedUrl"] == "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119-public.zip"


def test_unavailable_and_wrong_shape_failures_retain_evidence_before_reraising(tmp_path):
    transport, _calls = transport_for(b"gone", status=404)
    with pytest.raises(UslmSourceUnavailableError):
        capture(tmp_path / "gone", transport, route="statute-compilation", selection=StatuteCompilationSelection(1))
    receipt = json.loads((tmp_path / "gone" / "receipt.json").read_text())
    assert receipt["outcome"] == "failed"
    assert receipt["failure"]["type"] == "UslmSourceUnavailableError"
    assert receipt["failure"]["acquisition"]["selection"] == {"file_id": 1}
    assert receipt["failure"]["response"]["file"] == "refused-response.body"
    assert (tmp_path / "gone" / "refused-response.body").read_bytes() == b"gone"
    transport, _calls = transport_for(b"<html>Govinfo Bulkdata Service Error</html>", media_type="text/html")
    with pytest.raises(UslmSourceError):
        capture(tmp_path / "error-page", transport)
    receipt = json.loads((tmp_path / "error-page" / "receipt.json").read_text())
    assert receipt["failure"]["capture"]["statusCode"] == 200
    assert receipt["failure"]["response"]["mediaType"] == "text/html"


def test_output_directory_must_be_new_and_route_selection_must_agree(tmp_path):
    transport, calls = transport_for(LAW_XML)
    (tmp_path / "exists").mkdir()
    with pytest.raises(FileExistsError):
        capture(tmp_path / "exists", transport)
    with pytest.raises(ValueError, match="route and selection"):
        capture(tmp_path / "mismatch", transport, route="statute-compilation")
    assert not calls


def test_main_exits_two_with_the_refusal_and_makes_no_request(tmp_path, capsys):
    argv = ["public-law", "--congress", "0", "--number", "1", "--output", str(tmp_path / "bad"), "--max-bytes", "1024"]
    with pytest.raises(SystemExit) as raised:
        uslm_capture.main(argv)
    assert raised.value.code == 2
    assert "congress must be an integer" in capsys.readouterr().err
    assert not (tmp_path / "bad").exists()
