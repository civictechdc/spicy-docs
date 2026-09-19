"""One command walks any registered list route: exact page blobs, receipt rows, and refusals that exit non-zero."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.cli.list_pages import FAMILIES, main, parser, run
from spicy_docs.reading.paged_json import PagedJsonReader
from spicy_docs.sources.congress.listing import bill_list_url
from spicy_docs.sources.govinfo.discovery import package_granules_url

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
BILLS = (FIXTURES / "congress-bill-list.json").read_bytes()
GRANULES = (FIXTURES / "govinfo-package-granules.json").read_bytes()
RECIPIENTS = (FIXTURES / "usaspending-recipient-p1.json").read_bytes()
KEY = "k3y-abcdef0123456789"
GRANULES_URL = package_granules_url("CFR-2025-title1-vol1", page_size=2)


class Transport(httpx.MockTransport):
    def __init__(self, *bodies):
        self.bodies = iter(bodies)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return httpx.Response(
            200, stream=httpx.ByteStream(next(self.bodies)), headers={"content-type": "application/json"}
        )


@pytest.fixture
def store(tmp_path):
    return tmp_path / "blobs"


@pytest.fixture
def receipt(tmp_path):
    return tmp_path / "pages.jsonl"


@pytest.fixture
def walk(store, receipt):
    """Run the command offline against an injected transport, as the readers' own tests do."""

    def go(*arguments, transport=None):
        argv = [
            "--store",
            str(store),
            "--output",
            str(receipt),
            "--min-request-interval-seconds",
            "0",
            *arguments,
        ]
        code = run(parser().parse_args(argv), transport=transport)
        rows = [json.loads(line) for line in receipt.read_text().splitlines()]
        return code, rows, sorted((store / "sha256").glob("*")) if (store / "sha256").exists() else []

    return go


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(f"OTHER=unused\nAPI_GOV={KEY}\n")
    return str(path)


def test_registered_routes_state_each_publisher_contract_as_data():
    assert set(FAMILIES) == {
        "congress-bills",
        "congress-crs",
        "govinfo-packages",
        "govinfo-granules",
        "lda-filings",
        "courtlistener-search",
        "sam-entities",
        "usaspending-recipients",
        "fcc-proceedings",
        "fcc-filings",
        "regulations-gov-documents",
    }
    assert {name for name, route in FAMILIES.items() if route.env_var == "API_GOV"} == {
        "congress-bills",
        "congress-crs",
        "govinfo-packages",
        "govinfo-granules",
        "fcc-proceedings",
        "fcc-filings",
        "regulations-gov-documents",
    }
    assert FAMILIES["sam-entities"].env_var == "SAM_GOV"
    # LDA, CourtListener and USAspending name no variable: two take an optional token, one takes none at all.
    assert [name for name, route in FAMILIES.items() if route.env_var is None] == [
        "lda-filings",
        "courtlistener-search",
        "usaspending-recipients",
    ]
    assert not FAMILIES["usaspending-recipients"].family.credential_header
    assert [name for name, route in FAMILIES.items() if route.family.method == "POST"] == ["usaspending-recipients"]
    assert {route.records_key for route in FAMILIES.values()} == {
        "bills",
        "CRSReports",
        "packages",
        "granules",
        "results",
        "entityData",
        "proceeding",
        "filing",
        "data",
    }


def test_list_families_describes_every_route_offline(capsys):
    assert main(["--list-families"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["family"] for row in rows] == list(FAMILIES)
    assert all(row["kind"] == "family" for row in rows)
    recipients = next(row for row in rows if row["family"] == "usaspending-recipients")
    assert recipients["first_request"] == "body" and recipients["credential"] == "none"
    assert recipients["url"] == "https://api.usaspending.gov/api/v2/recipient/"
    granules = next(row for row in rows if row["family"] == "govinfo-granules")
    assert granules["first_request"] == "url" and granules["credential"] == "required"
    assert granules["records_key"] == "granules" and granules["env_var"] == "API_GOV"


def test_two_page_get_walk_writes_one_row_and_one_blob_per_page(walk, env_file, store):
    first = json.loads(BILLS)
    first["pagination"]["count"] = 4
    second = json.loads(BILLS)
    second["pagination"] = {"count": 4}
    bodies = (json.dumps(first).encode(), json.dumps(second).encode())
    transport = Transport(*bodies)
    code, rows, blobs = walk(
        "--family",
        "congress-bills",
        "--url",
        bill_list_url(limit=2),
        "--env-file",
        env_file,
        "--env-var",
        "API_GOV",
        "--max-pages",
        "50",
        transport=transport,
    )
    assert code == 0
    assert [row["kind"] for row in rows] == ["started", "page", "page", "complete"]
    pages = rows[1:3]
    assert [page["page_index"] for page in pages] == [0, 1]
    assert [page["records"] for page in pages] == [2, 2]
    assert [page["declared_count"] for page in pages] == [4, 4]
    assert [page["continuation_offered"] for page in pages] == [True, False]
    assert all(page["family"] == "congress-bills" and page["records_key"] == "bills" for page in pages)
    assert all(page["status"] == 200 and page["media_type"] == "application/json" for page in pages)
    assert all(page["request_url"] == page["resolved_url"] and page["request_body"] is None for page in pages)
    assert pages[1]["request_url"] == (
        "https://api.congress.gov/v3/bill?sort=updateDate+desc&offset=2&limit=2&format=json"
    )
    assert rows[-1]["pages"] == 2 and rows[-1]["records"] == 4 and rows[-1]["requests"] == 2
    # Each page's exact bytes are retained once, under the digest its row names.
    assert len(blobs) == 2
    for page, body in zip(pages, bodies, strict=True):
        assert page["sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
        assert (store / page["blob_path"]).read_bytes() == body and page["bytes"] == len(body)
    assert all(call.headers["x-api-key"] == KEY and "api_key" not in str(call.url) for call in transport.calls)


def test_post_family_records_its_request_body_beside_the_page(walk):
    only = json.loads(RECIPIENTS)
    only["page_metadata"] |= {"total": 2, "next": None, "hasNext": False}
    body = json.dumps(only).encode()
    transport = Transport(body)
    code, rows, blobs = walk(
        "--family",
        "usaspending-recipients",
        "--body",
        '{"limit":2,"page":1,"order":"desc","sort":"amount","award_type":"all"}',
        transport=transport,
    )
    assert code == 0
    assert [row["kind"] for row in rows] == ["started", "page", "complete"]
    page = rows[1]
    assert page["request_url"] == "https://api.usaspending.gov/api/v2/recipient/"
    assert page["request_body"] == {"limit": 2, "page": 1, "order": "desc", "sort": "amount", "award_type": "all"}
    assert page["records"] == 2 and page["declared_count"] == 2 and page["continuation_offered"] is False
    assert len(blobs) == 1 and blobs[0].read_bytes() == body
    assert transport.calls[0].method == "POST" and json.loads(transport.calls[0].read())["page"] == 1
    assert "authorization" not in transport.calls[0].headers and "x-api-key" not in transport.calls[0].headers


def test_a_family_needing_a_credential_refuses_before_any_request(walk):
    transport = Transport(GRANULES)
    code, rows, blobs = walk("--family", "govinfo-granules", "--url", GRANULES_URL, transport=transport)
    assert code == 1
    assert [row["kind"] for row in rows] == ["started", "failed"]
    assert rows[-1]["error"] == "GovInfo requires a credential; pass --env-file with --env-var API_GOV"
    assert rows[-1]["pages"] == 0 and rows[-1]["complete"] is False
    assert transport.calls == [] and blobs == []


def test_a_refused_page_writes_the_acquisition_context_and_retains_its_bytes(walk, env_file):
    refused = b'{"count":1,"nextPage":null}'
    transport = Transport(refused)
    code, rows, blobs = walk(
        "--family", "govinfo-granules", "--url", GRANULES_URL, "--env-file", env_file, transport=transport
    )
    assert code == 1
    assert [row["kind"] for row in rows] == ["started", "failed"]
    failure = rows[-1]
    assert failure["error_type"] == "PagedJsonSourceError"
    assert failure["error"] == "GovInfo list response omitted its granules list"
    assert failure["acquisition"] == {
        "operation": "page",
        "family": "govinfo",
        "url": GRANULES_URL,
        "requestBody": None,
        "pageIndex": 0,
        "recordsKey": "granules",
        "singleRecord": False,
        "requestCount": 1,
    }
    assert failure["refused_evidence"]["stage"] == "source-validation"
    assert failure["refused_evidence"]["bytes"] == len(refused)
    assert len(blobs) == 1 and blobs[0].read_bytes() == refused
    assert KEY not in json.dumps(rows)


def test_a_page_echoing_the_credential_retains_nothing(walk, env_file):
    echoed = json.dumps({"count": 1, "granules": [{"note": KEY}]}).encode()
    code, rows, blobs = walk(
        "--family", "govinfo-granules", "--url", GRANULES_URL, "--env-file", env_file, transport=Transport(echoed)
    )
    assert code == 1
    assert rows[-1]["kind"] == "failed" and rows[-1]["error_type"] == "CredentialRefusedError"
    assert "echoed" in rows[-1]["error"] and "refused_evidence" not in rows[-1]
    assert blobs == [] and KEY not in json.dumps(rows)


def test_no_receipt_row_keeps_a_credential_in_any_form(walk, env_file, receipt, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise ValueError(f"source refused https://api.govinfo.gov/x?api_key={KEY} and header {KEY}")
        yield

    monkeypatch.setattr(PagedJsonReader, "pages", refuse)
    code, rows, blobs = walk(
        "--family", "govinfo-granules", "--url", GRANULES_URL, "--env-file", env_file, transport=Transport()
    )
    assert code == 1 and rows[-1]["kind"] == "failed"
    # Both scrub passes must hold: the api_key= pattern and the literal key.
    assert KEY not in receipt.read_text() and receipt.read_text().count("<redacted>") == 2
    assert blobs == []


def test_an_existing_receipt_is_never_overwritten(store, receipt, capsys):
    receipt.write_text("kept\n")
    argv = ["--store", str(store), "--output", str(receipt), "--list-families"]
    assert run(parser().parse_args(argv)) == 1
    assert receipt.read_text() == "kept\n" and "exists" in capsys.readouterr().err


def test_missing_family_is_a_usage_error():
    with pytest.raises(SystemExit) as refusal:
        main(["--url", "https://api.govinfo.gov/x"])
    assert refusal.value.code == 2
