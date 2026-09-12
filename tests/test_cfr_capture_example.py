"""The runnable capture example retains exact bytes and truthful failure evidence."""

import gzip
import hashlib
import json
import socket
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx
import pytest

from examples import cfr_capture
from spicy_docs.sources.cfr.acquisition import CfrAcquisitionBudget, CfrSourceUnavailableError
from spicy_docs.sources.cfr.annual import annual_cfr_xml_locator
from spicy_docs.sources.cfr.ecfr import ecfr_bulk_xml_locator, ecfr_titles_locator, ecfr_xml_locator
from spicy_docs.sources.cfr.edition import annual_cfr_edition_locator
from spicy_docs.sources.cfr.models import AnnualCfrSelection, CfrSourceError, EcfrSelection
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "cfr"
BUDGET = CfrAcquisitionBudget(2, 65536, 7, 0)
NOW = datetime(2026, 9, 12, tzinfo=UTC)
SELECTION = EcfrSelection(1, "2026-08-10")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("capture example qualification must remain offline")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def transport_for(body, *, status=200, media_type="application/xml", content_encoding=None):
    calls = []

    def handle(request):
        calls.append(request)
        headers = {"content-type": media_type}
        if content_encoding:
            headers["content-encoding"] = content_encoding
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)

    return httpx.MockTransport(handle), calls


def capture(output, transport, *, budget=BUDGET, route="ecfr"):
    return cfr_capture.run_capture(
        output,
        route=route,
        selection=AnnualCfrSelection(2025, 1, 1) if route == "annual-edition" else SELECTION,
        budget=budget,
        transport=transport,
        clock=lambda: NOW,
    )


@pytest.mark.parametrize(
    "route,selection,fixture,locator",
    [
        ("ecfr-titles", None, "ecfr-titles.json", lambda _: ecfr_titles_locator()),
        ("ecfr", SELECTION, "ecfr-api-title1.xml", ecfr_xml_locator),
        ("ecfr", EcfrSelection(1, "2026-07-31", part="18"), "ecfr-api-part18.xml", ecfr_xml_locator),
        (
            "ecfr",
            EcfrSelection(1, "2026-07-31", part="18", section="18.1"),
            "ecfr-api-section18-1.xml",
            ecfr_xml_locator,
        ),
        ("annual", AnnualCfrSelection(2025, 1, 1), "annual-title1-vol1.xml", annual_cfr_xml_locator),
        (
            "annual",
            AnnualCfrSelection(2025, 30, 3, section="716.2"),
            "annual-title30-vol3-sec716-2.xml",
            annual_cfr_xml_locator,
        ),
        ("ecfr-bulk", 1, "ecfr-bulk-title1.xml", ecfr_bulk_xml_locator),
        ("annual-edition", AnnualCfrSelection(2025, 1, 1), "annual-title1-edition.xml", annual_cfr_edition_locator),
        (
            "annual-edition",
            AnnualCfrSelection(2023, 1, 1),
            "annual-title1-2023-edition.xml",
            annual_cfr_edition_locator,
        ),
    ],
)
def test_each_explicit_route_retains_original_and_evidence(tmp_path, route, selection, fixture, locator):
    body = (FIXTURES / fixture).read_bytes()
    media_type = "application/json" if route == "ecfr-titles" else "application/xml"
    transport, calls = transport_for(body, media_type=media_type)
    output = tmp_path / "new" / "capture"
    report = cfr_capture.run_capture(
        output, route=route, selection=selection, budget=BUDGET, transport=transport, clock=lambda: NOW
    )
    saved = json.loads((output / "receipt.json").read_text())
    assert saved == json.loads(json.dumps(report))
    assert saved["outcome"] == "captured"
    assert saved["requestCount"] == len(calls) == 1
    assert saved["budget"] == saved["requestedBudget"] == asdict(BUDGET)
    assert calls[0].method == "GET"
    assert str(calls[0].url) == saved["capture"]["requestedUrl"] == locator(selection)
    assert saved["capture"]["resolvedUrl"] == locator(selection)
    assert saved["capture"]["observedAt"] == "2026-09-12T00:00:00Z"
    assert saved["capture"]["contentEncoding"] == "identity"
    assert saved["capture"]["sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
    assert saved["capture"]["byteSize"] == len(body)
    assert (output / saved["capture"]["file"]).read_bytes() == body
    if route == "ecfr-titles":
        assert saved["source"]["titles"]["date"] == "2026-08-20"
        assert saved["source"]["titles"]["title_count"] == 50
        assert saved["selection"] is None
    elif route == "ecfr" and selection.part:
        assert saved["selection"]["title"] == 1
        assert saved["source"]["identity"]["title"] is None
        assert "title:request-url" in saved["source"]["identity"]["identity_basis"]
    elif route == "annual" and selection.title == 1:
        assert saved["selection"]["year"] == 2025
        assert "2023" in saved["source"]["identity"]["revision_text"]
    elif route == "ecfr-bulk":
        assert saved["selection"] == {"title": 1}
    elif route == "annual-edition":
        assert saved["source"]["edition"] == {
            "year": selection.year,
            "title": 1,
            "volume": 1,
            "date_issued": f"{selection.year}-01-01",
            "original_date_issued": "2023-01-01",
            "is_cover_only": selection.year == 2025,
            "edition_type": "cover-only" if selection.year == 2025 else "not-cover-only",
            "edition_id": "CFR-title1-vol1",
            "is_current_edition": selection.year == 2025,
            "is_fallback_title": False,
            "title_text": "General Provisions",
        }
        assert saved["capture"]["file"] == "response.xml"
        assert "xml" not in saved
    if route not in ("ecfr-titles", "annual-edition"):
        assert saved["xml"]["transformation"] == "identity"
        assert saved["xml"]["file"] == saved["capture"]["file"]
        assert saved["xml"]["sha256"] == saved["capture"]["sha256"]


def test_existing_output_is_untouched_before_any_request(tmp_path):
    (tmp_path / "receipt.json").write_bytes(b"previous evidence")
    transport, calls = transport_for(b"must not be requested")
    with pytest.raises(FileExistsError):
        capture(tmp_path, transport)
    assert not calls
    assert (tmp_path / "receipt.json").read_bytes() == b"previous evidence"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("status", [404, 410])
@pytest.mark.parametrize("route", ["ecfr", "annual-edition"])
def test_unavailable_locator_retains_failed_receipt_and_body_without_fallback(tmp_path, status, route):
    body = b"publisher says unavailable"
    transport, calls = transport_for(body, status=status)
    output = tmp_path / "capture"
    with pytest.raises(CfrSourceUnavailableError):
        capture(output, transport, route=route)
    saved = json.loads((output / "receipt.json").read_text())
    assert saved["outcome"] == "failed" and "capture" not in saved
    assert saved["failure"]["acquisition"]["requestCount"] == len(calls) == 1
    assert saved["failure"]["capture"]["statusCode"] == status
    assert saved["failure"]["capture"]["observedAt"] == "2026-09-12T00:00:00Z"
    assert (output / saved["failure"]["response"]["file"]).read_bytes() == body
    assert not (output / "response.xml").exists()


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("route", ["ecfr", "annual-edition"])
def test_access_refusal_records_omission_without_persisting_response_body(tmp_path, status, route):
    transport, calls = transport_for(b"sensitive challenge body", status=status)
    output = tmp_path / "capture"
    with pytest.raises(CredentialRefusedError):
        capture(output, transport, route=route)
    saved = json.loads((output / "receipt.json").read_text())
    assert saved["outcome"] == "failed"
    assert saved["failure"]["acquisition"]["requestCount"] == len(calls) == 1
    assert saved["failure"]["response"]["unavailableReason"]
    assert "file" not in saved["failure"]["response"]
    assert sorted(path.name for path in output.iterdir()) == ["receipt.json"]
    assert "sensitive challenge body" not in (output / "receipt.json").read_text()


def test_wrong_success_shape_retains_refused_source_bytes(tmp_path):
    body = b"<html>Challenge page</html>"
    transport, calls = transport_for(body)
    output = tmp_path / "capture"
    with pytest.raises(CfrSourceError):
        capture(output, transport)
    saved = json.loads((output / "receipt.json").read_text())
    assert saved["outcome"] == "failed"
    assert saved["failure"]["response"]["stage"] == "source-validation"
    assert (output / "refused-response.body").read_bytes() == body
    assert len(calls) == 1


def test_over_budget_response_has_omission_reason_and_no_partial_file(tmp_path):
    transport, _calls = transport_for((FIXTURES / "ecfr-api-title1.xml").read_bytes())
    output = tmp_path / "capture"
    with pytest.raises(CfrSourceError, match="byte bound"):
        capture(output, transport, budget=replace(BUDGET, max_bytes=10))
    saved = json.loads((output / "receipt.json").read_text())
    assert saved["outcome"] == "failed"
    assert saved["failure"]["acquisition"]["budget"]["max_bytes"] == 10
    assert saved["failure"]["response"]["unavailableReason"]
    assert sorted(path.name for path in output.iterdir()) == ["receipt.json"]


def test_gzip_retains_distinct_wire_response_and_decoded_xml(tmp_path):
    xml = (FIXTURES / "ecfr-api-title1.xml").read_bytes()
    wire = gzip.compress(xml, mtime=0)
    transport, calls = transport_for(wire, content_encoding="gzip")
    output = tmp_path / "capture"
    saved = capture(output, transport)
    assert saved["outcome"] == "captured" and len(calls) == 1
    assert saved["capture"]["contentEncoding"] == "gzip"
    assert saved["capture"]["file"] == "response.xml.gz"
    assert (output / "response.xml.gz").read_bytes() == wire
    assert (output / "response.xml").read_bytes() == xml
    assert saved["capture"]["byteSize"] == len(wire)
    assert saved["capture"]["sha256"] == "sha256:" + hashlib.sha256(wire).hexdigest()
    assert saved["xml"] == {
        "file": "response.xml",
        "byteSize": len(xml),
        "sha256": "sha256:" + hashlib.sha256(xml).hexdigest(),
        "transformation": "gzip-decode",
    }


@pytest.mark.parametrize("failure", ["malformed-gzip", "wrong-xml", "decoded-overrun"])
def test_complete_gzip_response_is_retained_when_decode_or_validation_fails(tmp_path, failure):
    budget = BUDGET
    if failure == "malformed-gzip":
        wire = b"not a gzip body"
    elif failure == "wrong-xml":
        wire = gzip.compress(b"<html>Challenge page</html>", mtime=0)
    else:
        wire = gzip.compress(b"<ECFR>" + b" " * 2000 + b"</ECFR>", mtime=0)
        budget = replace(BUDGET, max_bytes=100)
        assert len(wire) < budget.max_bytes
    transport, calls = transport_for(wire, content_encoding="gzip")
    output = tmp_path / "capture"
    with pytest.raises(CfrSourceError):
        capture(output, transport, budget=budget)
    saved = json.loads((output / "receipt.json").read_text())
    assert saved["outcome"] == "failed" and len(calls) == 1
    assert saved["failure"]["capture"]["contentEncoding"] == "gzip"
    assert saved["failure"]["capture"]["sha256"] == "sha256:" + hashlib.sha256(wire).hexdigest()
    assert (output / "refused-response.body").read_bytes() == wire
    assert not (output / "response.xml").exists()


def test_cli_uses_explicit_date_and_byte_bound(tmp_path, monkeypatch, capsys):
    transport, calls = transport_for((FIXTURES / "ecfr-api-title1.xml").read_bytes())
    monkeypatch.setattr(cfr_capture, "run_capture", partial(cfr_capture.run_capture, transport=transport))
    assert (
        cfr_capture.main(
            ["ecfr", "--title", "1", "--date", "2026-08-10", "--max-bytes", "65536", "--output", str(tmp_path / "out")]
        )
        == 0
    )
    saved = json.loads(capsys.readouterr().out)
    assert saved["outcome"] == "captured"
    assert saved["selection"]["date"] == "2026-08-10"
    assert saved["budget"]["max_bytes"] == 65536
    assert str(calls[0].url) == ecfr_xml_locator(SELECTION)


@pytest.mark.parametrize("missing", ["--date", "--max-bytes"])
def test_cli_requires_date_and_byte_bound_before_starting(tmp_path, missing):
    args = ["ecfr", "--title", "1", "--date", "2026-08-10", "--max-bytes", "65536", "--output", str(tmp_path / "out")]
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit, match="2"):
        cfr_capture.main(args)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("missing", ["--year", "--title", "--volume"])
def test_edition_cli_requires_each_package_selector(tmp_path, missing):
    args = [
        "annual-edition",
        "--year",
        "2025",
        "--title",
        "1",
        "--volume",
        "1",
        "--max-bytes",
        "65536",
        "--output",
        str(tmp_path / "out"),
    ]
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit, match="2"):
        cfr_capture.main(args)
    assert not (tmp_path / "out").exists()


def test_edition_cli_refuses_section_selector(tmp_path):
    with pytest.raises(SystemExit, match="2"):
        cfr_capture.main(
            [
                "annual-edition",
                "--year",
                "2025",
                "--title",
                "1",
                "--volume",
                "1",
                "--section",
                "1.1",
                "--max-bytes",
                "65536",
                "--output",
                str(tmp_path / "out"),
            ]
        )
    assert not (tmp_path / "out").exists()


def test_edition_cli_captures_only_the_selected_volume_metadata(tmp_path, monkeypatch, capsys):
    body = (FIXTURES / "annual-title1-edition.xml").read_bytes()
    transport, calls = transport_for(body)
    monkeypatch.setattr(cfr_capture, "run_capture", partial(cfr_capture.run_capture, transport=transport))
    args = ["annual-edition", "--year", "2025", "--title", "1", "--volume", "1", "--max-bytes", "65536"]
    assert cfr_capture.main([*args, "--output", str(tmp_path / "out")]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["outcome"] == "captured"
    assert saved["source"]["edition"]["edition_type"] == "cover-only"
    assert saved["selection"] == {"year": 2025, "title": 1, "volume": 1, "section": None}
    assert saved["requestCount"] == len(calls) == 1
    assert str(calls[0].url) == annual_cfr_edition_locator(AnnualCfrSelection(2025, 1, 1))
    assert (tmp_path / "out" / "response.xml").read_bytes() == body


def test_absent_cover_flag_stays_unknown_in_the_edition_receipt(tmp_path):
    body = (FIXTURES / "annual-title1-edition.xml").read_bytes()
    assert b"<isCoverOnly>true</isCoverOnly>" in body
    body = body.replace(b"<isCoverOnly>true</isCoverOnly>", b"")
    transport, _calls = transport_for(body)
    saved = capture(tmp_path / "out", transport, route="annual-edition")
    assert saved["source"]["edition"]["is_cover_only"] is None
    assert saved["source"]["edition"]["edition_type"] == "unknown"
    assert (tmp_path / "out" / "response.xml").read_bytes() == body
