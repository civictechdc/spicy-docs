"""Known-answer metadata, source-loss, refusal and resume controls for the AO example."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from rulespec_artifacts import LocalBlobWriter

from spicy_docs.reading.s3_listing import NAMESPACE
from spicy_docs.sources.fec.catalog import BUCKET, BUCKET_URL
from spicy_docs.sources.fec.client import FecClient
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.download import HttpRefusal

spec = importlib.util.spec_from_file_location(
    "fec_legal_year", Path(__file__).parents[1] / "examples/fec_legal_year.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
PDF = b"%PDF-1.4\nretained fixture\n%%EOF"
KEY = "legal/aos/2024-01/request.pdf"
URL = BUCKET_URL + KEY


def fixture_client(
    root,
    *,
    empty=False,
    source_change=None,
    fail_asset=False,
    deny_api=False,
    invalid_api=False,
    wrong_detail=False,
    listing_only=False,
):
    """A scripted client serving retained fixtures with pinned request assertions."""
    calls = []
    case = {
        "ao_no": "2024-01",
        "status": "Withdrawn",
        "is_pending": False,
        "unknown": {"missing_is_distinct": None, "empty": []},
        "documents": [
            {"document_id": 1, "category": "Request", "url": "/files/" + KEY, "text": "Exact body\n"},
            {"document_id": 2, "category": "Supplement", "url": "/files/" + KEY},
            {"document_id": 3, "category": "Withdrawn", "url": None},
        ],
    }
    if source_change:
        source_change(case)

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "api.open.fec.gov":
            assert request.headers["X-Api-Key"] == "fixture-key"
            if deny_api:
                return httpx.Response(403)
            if invalid_api:
                return httpx.Response(
                    200, content=b"<html>publisher challenge</html>", headers={"Content-Type": "text/html"}
                )
            if request.url.path == "/v1/legal/search/":
                return httpx.Response(
                    200,
                    json={"advisory_opinions": [] if empty else [case], "total_advisory_opinions": 0 if empty else 1},
                )
            if listing_only and request.url.path == "/v1/legal/docs/advisory_opinions/2024-02":
                return httpx.Response(200, json={"docs": []})
            assert request.url.path == "/v1/legal/docs/advisory_opinions/2024-01"
            return httpx.Response(
                200, json={"docs": [] if empty else [{**case, "ao_no": "2024-02"} if wrong_detail else case]}
            )
        assert "X-Api-Key" not in request.headers
        if request.url.path == "/":
            content = (
                ""
                if empty
                else (
                    f'<Contents><Key>{KEY}</Key><Size>{len(PDF)}</Size><ETag>"e"</ETag>'
                    "<LastModified>2026-09-13T00:00:00Z</LastModified></Contents>"
                )
            )
            if listing_only:
                content += content.replace("2024-01", "2024-02")
            listing = (
                f'<ListBucketResult xmlns="{NAMESPACE}"><Name>{BUCKET}</Name>'
                "<Prefix>legal/aos/2024-</Prefix><IsTruncated>false</IsTruncated>"
                f"{content}</ListBucketResult>"
            )
            return httpx.Response(200, content=listing, headers={"Content-Type": "application/xml"})
        assert str(request.url) in ({URL, URL.replace("2024-01", "2024-02")} if listing_only else {URL})
        assert request.headers["If-Match"] == '"e"'
        status = fail_asset if type(fail_asset) is int else 404 if fail_asset else 200
        return httpx.Response(status, content=PDF, headers={"Content-Type": "application/pdf", "ETag": '"e"'})

    # The replayed API states no quota; OpenFEC pacing is pinned in test_fec.py.
    return FecClient(
        store=root / "blobs",
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
        min_interval=0,
        rate_limit=None,
    ), calls


def prepared(tmp_path, **options):
    """Run the example against a prepared temp directory and return its plan."""
    with fixture_client(tmp_path, **options)[0] as client:
        example.capture_metadata(client, tmp_path, 2024)
    return example.load_plan(tmp_path)[1]


def test_complete_capture_preserves_nested_status_body_and_repeated_associations(tmp_path):
    """A complete capture preserves nested status, body and repeated associations, acquiring one original with no
    re-request on verify.
    """
    plan = prepared(tmp_path)
    assert len(plan["originals"]) == 1
    item = plan["originals"][0]
    assert item["url"] == URL
    # Search/detail and repeated document associations remain separately visible.
    assert len(item["associations"]) == 4
    assert len(plan["unavailable"]) == 2
    manifest = json.loads((tmp_path / "selection.json").read_bytes())
    metadata = (tmp_path / manifest["metadata"]["file"]).read_text()
    assert '"status": "Withdrawn"' in metadata
    assert '"empty": []' in metadata and '"missing_is_distinct": null' in metadata
    assert '"embedded_bodies": [{"characters": 11' in metadata
    client, calls = fixture_client(tmp_path)
    with client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF))
    assert calls == [URL]
    report = example.verify(tmp_path)
    assert report["counts"] == {"acquired": 1}
    assert report["acquired_bytes"] == len(PDF)
    client, calls = fixture_client(tmp_path)
    with client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF))
    assert calls == []


def test_empty_observation_has_no_invented_absence_or_body(tmp_path):
    """An empty observation invents no absence or body and reports no counts."""
    plan = prepared(tmp_path, empty=True)
    assert plan == {"originals": [], "unavailable": [], "cases": []}
    client, calls = fixture_client(tmp_path, empty=True)
    with client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=1)
    assert not calls
    assert example.verify(tmp_path)["counts"] == {}


def test_extensionless_supporting_document_and_external_url_are_not_silently_dropped(tmp_path):
    """Extensionless supporting documents and external URLs are not silently dropped."""

    def change(case):
        case["documents"] += [{"url": "/download/legal/document?id=1"}, {"url": "https://external.test/item.pdf"}]
        case["ao_citations"] = [{"ao_no": "1975-01", "url": "/files/legal/aos/1975-01/opinion.pdf"}]

    plan = prepared(tmp_path, source_change=change)
    assert [item["url"] for item in plan["originals"]] == [URL, "https://www.fec.gov/download/legal/document?id=1"]
    external = [row for row in plan["unavailable"] if row["disposition"] == "unavailable-outside-approved-hosts"]
    assert len(external) == 2
    assert all(row["source_url"] == "https://external.test/item.pdf" for row in external)


def test_wrong_detail_identity_never_binds_a_complete_selection_and_can_retry(tmp_path):
    """A wrong detail identity never binds a complete selection and the case can retry."""
    client, _ = fixture_client(tmp_path, wrong_detail=True)
    with client, pytest.raises(ValueError, match="detail identity"):
        example.capture_metadata(client, tmp_path, 2024)
    assert not (tmp_path / "selection.json").exists()
    assert json.loads(next(tmp_path.glob("*.failure.json")).read_bytes())["operation"] == "metadata-validation"
    client, calls = fixture_client(tmp_path)
    with client:
        example.capture_metadata(client, tmp_path, 2024)
    assert len(calls) == 3
    assert example.load_plan(tmp_path)[1]["cases"][0]["disposition"] == "returned"


def test_listing_only_case_is_requested_and_retained_with_empty_detail_outcome(tmp_path):
    """A listing-only case is requested and retained with an empty detail outcome."""
    client, calls = fixture_client(tmp_path, listing_only=True, source_change=lambda case: case["documents"].pop())
    with client:
        example.capture_metadata(client, tmp_path, 2024)
        plan = example.load_plan(tmp_path)[1]
        example.acquire_originals(client, tmp_path, plan, max_bytes=2 * len(PDF))
    assert len(plan["originals"]) == 2
    assert plan["unavailable"] == []
    assert [(case["ao_no"], case["disposition"]) for case in plan["cases"]] == [
        ("2024-01", "returned"),
        ("2024-02", "requested-empty"),
    ]
    assert "https://api.open.fec.gov/v1/legal/docs/advisory_opinions/2024-02" in calls
    report = example.verify(tmp_path)
    assert report["counts"] == {"acquired": 2}
    assert report["acquisition_complete"] is False


def test_byte_bound_is_explicit_and_every_failed_original_is_retried(tmp_path):
    """The byte bound is explicit and every failed original is retried."""
    plan = prepared(tmp_path)
    client, calls = fixture_client(tmp_path)
    with client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF) - 1)
    assert not calls
    assert example.verify(tmp_path)["counts"] == {"unrequested-byte-bound": 1}
    client, calls = fixture_client(tmp_path, fail_asset=True)
    with client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF))
    assert calls == [URL]
    assert example.verify(tmp_path)["counts"] == {"failed": 1}
    client, calls = fixture_client(tmp_path)
    with client:
        rows = example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF))
    assert calls == [URL] and len(rows[0]["attempts"]) == 1
    assert example.verify(tmp_path)["counts"] == {"acquired": 1}


def test_api_credential_refusal_stops_without_a_complete_metadata_manifest(tmp_path):
    """An API credential refusal stops without a complete metadata manifest."""
    client, calls = fixture_client(tmp_path, deny_api=True)
    with client, pytest.raises(HttpRefusal):
        example.capture_metadata(client, tmp_path, 2024)
    assert len(calls) == 2
    assert not (tmp_path / "selection.json").exists()
    assert len(list(tmp_path.glob("metadata-*.jsonl"))) == 1
    failure = json.loads(next(tmp_path.glob("*.failure.json")).read_bytes())
    assert failure["operation"] == "search" and failure["complete"] is False


def test_metadata_shape_refusal_retains_exact_bytes_and_stage(tmp_path):
    """A metadata shape refusal retains exact bytes and the source-validation stage."""
    client, _ = fixture_client(tmp_path, invalid_api=True)
    with client, pytest.raises(ValueError):
        example.capture_metadata(client, tmp_path, 2024)
    failure = json.loads(next(tmp_path.glob("*.failure.json")).read_bytes())
    assert failure["refused_evidence"]["stage"] == "source-validation"
    assert example.blob_bytes(tmp_path / "blobs", failure["refused_evidence"]) == b"<html>publisher challenge</html>"
    assert not (tmp_path / "selection.json").exists()


def test_credential_refusal_stops_original_requests_and_scrubs_error(tmp_path):
    """A credential refusal stops original requests, marks later ones unrequested and scrubs the error."""
    plan = prepared(tmp_path)
    plan["originals"].append({"url": BUCKET_URL + "legal/aos/2024-01/other.pdf", "listing": None, "associations": []})

    class RefusedClient:
        calls = 0

        def download(self, *args, **kwargs):
            self.calls += 1
            raise CredentialRefusedError("refused fixture-secret-123")

    client = RefusedClient()
    with pytest.raises(CredentialRefusedError):
        example.acquire_originals(client, tmp_path, plan, max_bytes=1000, secret="fixture-secret-123")
    rows = example.original_rows(tmp_path)
    assert client.calls == 1
    assert [row["disposition"] for row in rows] == ["failed", "unrequested"]
    assert "fixture-secret-123" not in example.encoded(rows).decode()


def test_actual_etag_bound_download_keeps_http_403_as_a_stop(tmp_path):
    """An ETag-bound download keeps an HTTP 403 as a stop."""
    plan = prepared(tmp_path)
    client, calls = fixture_client(tmp_path, fail_asset=403)
    with client, pytest.raises(HttpRefusal) as caught:
        example.acquire_originals(client, tmp_path, plan, max_bytes=1000)
    assert caught.value.status == 403 and calls == [URL]
    assert example.original_rows(tmp_path)[0]["disposition"] == "failed"


def test_verified_incomplete_capture_has_nonzero_command_status(tmp_path, monkeypatch):
    """A verified incomplete capture exits non-zero."""
    plan = prepared(tmp_path)
    with fixture_client(tmp_path)[0] as client:
        example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF) - 1)
    monkeypatch.setattr("sys.argv", [str(Path(example.__file__)), str(tmp_path), "--verify-only"])
    assert example.main() == 2
    assert example.verify(tmp_path)["acquisition_complete"] is False


def test_interrupted_original_run_resumes_from_atomic_per_object_checkpoints(tmp_path, monkeypatch):
    """An interrupted original run resumes from atomic per-object checkpoints, replacing no complete state."""
    plan = prepared(tmp_path)
    second = {"url": BUCKET_URL + "legal/aos/2024-01/other.pdf", "listing": None, "associations": []}
    plan["originals"].append(second)
    snapshots = []
    save = example.save

    def counted_save(path, value):
        if path.name == "originals.json":
            snapshots.append(len(value))
        save(path, value)

    monkeypatch.setattr(example, "save", counted_save)

    class Client:
        def __init__(self):
            self.calls = []
            self.interrupt = True

        def download(self, url, **kwargs):
            self.calls.append(url)
            if self.interrupt and url == second["url"]:
                raise KeyboardInterrupt
            written = LocalBlobWriter(tmp_path / "blobs").put([PDF], max_bytes=1000)
            return {"url": url, "sha256": written.digest, "bytes": written.byte_size}

    client = Client()
    with pytest.raises(KeyboardInterrupt):
        example.acquire_originals(client, tmp_path, plan, max_bytes=1000)
    assert [row["disposition"] for row in example.original_rows(tmp_path)] == ["acquired", "unrequested"]
    # A killed atomic write's temporary bytes cannot replace its last complete state.
    checkpoint = next((tmp_path / "original-progress").glob("*.json"))
    checkpoint.with_suffix(".json.tmp").write_bytes(b"{truncated")
    client.interrupt = False
    client.calls.clear()
    rows = example.acquire_originals(client, tmp_path, plan, max_bytes=1000)
    assert client.calls == [second["url"]]
    assert all(row["disposition"] == "acquired" for row in rows)
    assert snapshots == [2, 2, 2]  # Start of interrupted run; start/end of resumed run.


@pytest.mark.parametrize("change", ["status", "supporting-url", "empty-list", "body-pointer", "source-bytes"])
def test_retained_replay_detects_source_loss_even_when_metadata_file_is_repinned(tmp_path, change):
    """Retained replay detects source loss even when the metadata file is repinned."""
    prepared(tmp_path)
    manifest = json.loads((tmp_path / "selection.json").read_bytes())
    path = tmp_path / manifest["metadata"]["file"]
    events = [json.loads(line) for line in path.read_bytes().splitlines()]
    record = events[1]["page"]["records"][0]
    if change == "status":
        record["metadata"]["status"] = "Final"
    elif change == "supporting-url":
        record["metadata"]["documents"].pop()
    elif change == "empty-list":
        del record["metadata"]["unknown"]["empty"]
    elif change == "body-pointer":
        record["embedded_bodies"][0]["source_pointer"] = "/wrong"
    else:
        events[1]["page"]["evidence"]["bytes"] += 1
    path.write_bytes(b"".join(example.encoded(event) + b"\n" for event in events))
    manifest["metadata"] = example.pin(path)
    example.save(tmp_path / "selection.json", manifest)
    with pytest.raises(ValueError, match="retained"):
        example.load_plan(tmp_path)


def test_original_membership_and_association_mutation_is_rejected(tmp_path):
    """A membership or association mutation is rejected."""
    plan = prepared(tmp_path)
    with fixture_client(tmp_path)[0] as client:
        rows = example.acquire_originals(client, tmp_path, plan, max_bytes=len(PDF))
    changed = copy.deepcopy(rows)
    changed[0]["selected"]["associations"].pop()
    example.save(tmp_path / "originals.json", changed)
    with pytest.raises(ValueError, match="association"):
        example.verify(tmp_path)


def test_wrong_year_is_rejected_before_original_acquisition(tmp_path):
    """A wrong year is rejected before any original acquisition."""
    client, calls = fixture_client(tmp_path, source_change=lambda row: row.update(ao_no="2023-01"))
    with client, pytest.raises(ValueError, match="outside"):
        example.capture_metadata(client, tmp_path, 2024)
    assert len(calls) == 2
