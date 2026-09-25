"""CFTC PDF measurements enforce sample bounds and retain successful and failed outcomes offline."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.sources import walled_fetch as walled_fetch_module
from spicy_docs.sources.cftc_comments.acquisition import CftcPortalAcquirer, CftcPortalBudget
from spicy_docs.sources.cftc_comments.pages import comment_list_url
from spicy_docs.sources.walled_fetch import RungOutcome, Transport, WalledFetchResult, _exhausted
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tools.analysis import cftc_pdf_bounds as tool

PDF = b"%PDF-1.4\ntrailer\n<<>>\n%%EOF\n"
FIXTURES = Path(__file__).parent / "fixtures" / "cftc_comments"
REAL_HARVEST = tool._harvest


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "require_zyte_token_from_environment", lambda: "test-token")
    monkeypatch.setattr(tool, "require_firecrawl_api_key_from_environment", lambda: "test-key")
    monkeypatch.setattr(tool, "MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(tool, "BLOB_STORE", tmp_path / "blobs")
    monkeypatch.setattr(tool, "_harvest", lambda *_: [])
    monkeypatch.setattr(walled_fetch_module, "walled_fetch", lambda *_a, **_k: pytest.fail("unscripted request"))


def result(url, body=PDF, status=200, content_type="application/pdf"):
    return WalledFetchResult(body, status, content_type, url, Transport.DIRECT, None, None)


def receipt(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_sample_narrows_each_download_to_the_remaining_cumulative_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "PDF_BYTE_CAP", len(PDF))
    monkeypatch.setattr(tool, "CUMULATIVE_BYTE_BUDGET", len(PDF) * 2 + 5)
    calls = []

    def fetch(url, *, max_bytes, **kwargs):
        kwargs["before_request"]()
        calls.append(max_bytes)
        return result(url, PDF[:max_bytes])

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", fetch)
    path = tmp_path / "receipt.jsonl"
    assert tool.run(path) == 0
    header, *rows = receipt(path)
    assert calls == [len(PDF), len(PDF), 5]
    assert header["downloadedBytes"] == tool.CUMULATIVE_BYTE_BUDGET
    assert [row["outcome"] for row in rows] == ["complete", "complete", "invalid"]
    assert rows[0]["pdfVersion"] == "1.4"
    store = LocalSourceNativeBlobStore(tool.BLOB_STORE, create=False)
    with store.open(rows[0]["blobRef"]) as handle:
        assert handle.read() == PDF
    assert rows[0]["sha256"] == "sha256:" + hashlib.sha256(PDF).hexdigest()
    assert rows[2].get("blobRef") is None


def test_failed_downloads_still_write_a_receipt_and_harvested_ids_are_deduplicated(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_harvest", lambda *_: [(25524, "duplicate seed"), (22, "fresh"), (22, "repeat")])
    monkeypatch.setattr(tool, "MAX_PDF_FETCHES", 4)
    calls = []

    def fetch(url, **kwargs):
        kwargs["before_request"]()
        calls.append(url)
        if len(calls) == 1:
            outcome = RungOutcome(Transport.DIRECT, "wall", body=b"Access Denied")
            raise _exhausted(url, (outcome,), outcome.body)
        if len(calls) == 2:
            return result(url, b"missing", status=404)
        return result(url)

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", fetch)
    monkeypatch.setattr(tool, "_retain_blob", lambda *_: "blob-write-failed: disk full")
    path = tmp_path / "receipt.jsonl"
    assert tool.run(path) == 0
    header, *rows = receipt(path)
    assert [row["fileId"] for row in rows] == [25524, 10, 10000, 22]
    assert [row["outcome"] for row in rows] == ["refused", "unavailable", "complete", "complete"]
    assert rows[0]["rungOutcomes"][0]["kind"] == "wall"
    assert rows[1]["status"] == 404
    assert rows[2]["blobRef"] is None and "disk full" in rows[2]["blobError"]
    assert len(calls) == 4
    assert header["downloadedBytes"] == sum(row.get("byteSize") or 0 for row in rows)


def test_harvest_reads_pages_through_the_production_acquirer_and_records_every_outcome(monkeypatch):
    calls = []

    def fetch(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            return result(url, (FIXTURES / "comment-list-1647.html").read_bytes(), content_type="text/html")
        if len(calls) == 2:
            outcome = RungOutcome(Transport.DIRECT, "wall", body=b"Attention Required! | Cloudflare")
            raise _exhausted(url, (outcome,), outcome.body)
        return result(url, b"<html>wrong page</html>", content_type="text/html")

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", fetch)
    records = []
    with CftcPortalAcquirer(budget=CftcPortalBudget(3, 1024**2, 7, 0), recover_walls=True) as portal:
        fresh = REAL_HARVEST(records, portal)
    assert fresh == []
    assert calls[0] == comment_list_url(1647)
    assert len(calls) == 1 + tool.MAX_HARVEST_DETAILS
    assert [record["outcome"] for record in records] == ["fetched", "exhausted", "refused", "refused"]
    assert records[1]["refusalKind"] == "cloudflare-blocked" and records[1]["rungOutcomes"][0]["kind"] == "wall"


def test_an_existing_receipt_is_refused_before_any_request(tmp_path, capsys):
    # The autouse fixture fails any ladder request, so a refusal here made none.
    path = tmp_path / "receipt.jsonl"
    path.write_text("retained\n")
    assert tool.main(["--receipt", str(path)]) == 2
    assert path.read_text() == "retained\n"
    assert "already exists" in capsys.readouterr().err
