"""One BILLSTATUS folder zip: every member proved or refused, and the bounds that refuse the zip.

The archive under test is built here from complete, unchanged members of the
119th H.Res. zip (`tests/fixtures/govinfo_bills/README.md`), plus two members
that cannot be what their names claim. Building it here keeps every byte of the
archive reviewable; the publisher's own zip is the live test below.
"""

import hashlib
import zipfile
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.bill_acquisition import BillSourceUnavailableError
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError
from spicy_docs.sources.congress.bulk_status import (
    BulkStatusAcquirer,
    BulkStatusBudget,
    bulk_status_locator,
    read_bulk_status_archive,
)
from spicy_docs.transport import retry
from tests.source_fixtures import archive_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
PLAIN = (FIXTURES / "status-119hres1376.xml").read_bytes()
CDATA = (FIXTURES / "status-119hres10.xml").read_bytes()
UNTEXTED_ACTION = (FIXTURES / "status-119hres214.xml").read_bytes()
FOREIGN = b"not a BILLSTATUS file"
MEMBERS = (
    ("BILLSTATUS-119hres10.xml", CDATA),
    ("readme.txt", FOREIGN),
    ("BILLSTATUS-119hres1376.xml", PLAIN),
    # The same bytes under another bill's name: the XML states H.Res. 10.
    ("BILLSTATUS-119hres11.xml", CDATA),
    ("BILLSTATUS-119hres214.xml", UNTEXTED_ACTION),
)
ZIP = archive_bytes(*MEMBERS)
URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hres/BILLSTATUS-119-hres.zip"
BUDGET = BulkStatusBudget(2, 4 * 1024 * 1024, 7, 0)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def response(body=ZIP, status=200, *, content_type="application/zip"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_every_member_is_proved_or_refused_in_the_publisher_order():
    result = read_bulk_status_archive(ZIP, congress=119, bill_type="hres")
    assert [member.name for member in result.members] == [name for name, _ in MEMBERS]
    assert (len(result.members), result.parsed_count, result.refused_count) == (5, 3, 2)
    assert [member.byte_size for member in result.members] == [len(data) for _, data in MEMBERS]
    assert [member.sha256 for member in result.members] == [digest(data) for _, data in MEMBERS]

    wrapped, unnamed, plain, mismatched, untexted = result.members
    assert wrapped.identity == BillIdentity(119, "hres", 10)
    assert wrapped.refusal is None
    assert wrapped.status.title == "HEALTH Act"
    assert wrapped.status.summaries[0].text_in_cdata is True
    assert wrapped.status.summaries[0].text.startswith("<p><strong>House Endeavor")

    assert plain.status.summaries[0].text_in_cdata is False
    assert plain.status.text_versions[0].package_id == "BILLS-119hres1376ih"
    # The one measured action without text; every other field of it survives.
    assert untexted.status.actions[-1].text is None
    assert (untexted.status.actions[-1].action_code, untexted.status.actions[-1].action_type) == (
        "Intro-H",
        "IntroReferral",
    )

    assert (unnamed.identity, unnamed.status) == (None, None)
    assert unnamed.refusal == "BILLSTATUS archive entry name does not state a bill identity"
    assert (mismatched.identity, mismatched.status) == (BillIdentity(119, "hres", 11), None)
    assert mismatched.refusal == "BILLSTATUS XML identity differs from the requested bill"


@pytest.mark.parametrize(
    "name,refusal",
    [
        ("BILLSTATUS-118hres10.xml", "belongs to another Congress or bill type"),
        ("BILLSTATUS-119hr10.xml", "belongs to another Congress or bill type"),
        ("BILLSTATUS-119hres010.xml", "does not state a bill identity"),
        ("BILLSTATUS-119hres10.XML", "does not state a bill identity"),
        ("BILLSTATUS-119hres10.xml.bak", "does not state a bill identity"),
        ("BILLSTATUS-119hres0.xml", "does not state a bill identity"),
    ],
)
def test_a_member_name_that_is_not_this_folder_is_one_refused_outcome(name, refusal):
    result = read_bulk_status_archive(archive_bytes((name, CDATA)), congress=119, bill_type="hres")
    assert result.refused_count == 1 and result.parsed_count == 0
    assert refusal in result.members[0].refusal
    assert result.members[0].sha256 == digest(CDATA)


def test_a_member_in_a_folder_path_is_read_by_its_own_file_name():
    result = read_bulk_status_archive(
        archive_bytes(("119/hres/BILLSTATUS-119hres10.xml", CDATA)), congress=119, bill_type="hres"
    )
    assert result.parsed_count == 1
    assert result.members[0].name == "119/hres/BILLSTATUS-119hres10.xml"
    assert result.members[0].identity == BillIdentity(119, "hres", 10)


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"max_entries": 4}, "more entries than max_entries"),
        ({"max_entry_bytes": len(CDATA) - 1}, "exceeds max_entry_bytes"),
        ({"max_total_bytes": len(CDATA)}, "exceeds max_total_bytes"),
        ({"max_bytes": len(ZIP) - 1}, "within max_bytes"),
        ({"max_entries": 0}, "max_entries"),
        ({"max_entry_bytes": 0}, "max_entry_bytes"),
    ],
)
def test_archive_bounds_refuse_the_whole_zip_rather_than_one_member(kwargs, message):
    with pytest.raises(BillSourceError, match=message):
        read_bulk_status_archive(ZIP, congress=119, bill_type="hres", **kwargs)


@pytest.mark.parametrize("body", [b"", b"PK", b"<html>not a zip</html>", ZIP[:-1], ZIP[4:]])
def test_a_response_that_is_not_an_archive_is_refused_before_any_member_is_trusted(body):
    with pytest.raises(BillSourceError):
        read_bulk_status_archive(body, congress=119, bill_type="hres")


def test_a_corrupted_member_refuses_the_zip_rather_than_reaching_the_others():
    body = bytearray(archive_bytes(("BILLSTATUS-119hres10.xml", CDATA), compression=zipfile.ZIP_STORED))
    offset = body.index(b"<billStatus>")
    body[offset : offset + 1] = b" "
    with pytest.raises(BillSourceError, match="fails its CRC check"):
        read_bulk_status_archive(bytes(body), congress=119, bill_type="hres")


def test_locator_is_the_keyless_publisher_folder_and_refuses_anything_else():
    assert bulk_status_locator(119, "hres") == URL
    assert bulk_status_locator(108, "s") == ("https://www.govinfo.gov/bulkdata/BILLSTATUS/108/s/BILLSTATUS-108-s.zip")
    for congress, bill_type in [
        (119, "HRES"),
        (119, "hres/../hr"),
        (119, "bill"),
        (119, ""),
        (0, "hres"),
        (True, "hres"),
        ("119", "hres"),
    ]:
        with pytest.raises(BillSourceError):
            bulk_status_locator(congress, bill_type)


@pytest.mark.parametrize("content_type", ["application/zip", "application/octet-stream", "application/zip; x=1"])
def test_capture_keeps_the_exact_zip_and_the_facts_that_locate_it(content_type):
    transport = Transport(response(content_type=content_type))
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(119, "hres")
    assert result.capture.body == ZIP
    assert result.capture.requested_url == URL and result.capture.resolved_url == URL
    assert (result.capture.status_code, result.capture.byte_size) == (200, len(ZIP))
    assert result.capture.sha256 == digest(ZIP)
    assert result.capture.content_type == content_type
    assert result.capture.observed_at.endswith("Z")
    assert (result.archive.congress, result.archive.bill_type) == (119, "hres")
    assert (result.archive.parsed_count, result.archive.refused_count) == (3, 2)
    assert (result.request_count, result.budget) == (1, BUDGET)
    assert transport.calls[0].method == "GET"
    assert "api_key" not in str(transport.calls[0].url) and not transport.calls[0].url.query


def test_a_zip_larger_than_the_budget_is_refused_by_the_transport():
    budget = BulkStatusBudget(2, len(ZIP) - 1, 7, 0)
    with (
        BulkStatusAcquirer(budget=budget, transport=Transport(response())) as source,
        pytest.raises(BillSourceError, match="exceeds its byte bound"),
    ):
        source.acquire(119, "hres")


def test_missing_folder_wrong_format_and_failures_carry_their_capture_and_context():
    with (
        BulkStatusAcquirer(budget=BUDGET, transport=Transport(response(b"missing", 404))) as source,
        pytest.raises(BillSourceUnavailableError) as unavailable,
    ):
        source.acquire(119, "hres")
    assert unavailable.value.capture.status_code == 404
    assert unavailable.value.capture.body == b"missing"
    assert unavailable.value.bulk_status_acquisition["selection"] == {"congress": 119, "billType": "hres"}

    with (
        BulkStatusAcquirer(budget=BUDGET, transport=Transport(response(content_type="text/html"))) as source,
        pytest.raises(BillSourceError, match="Content-Type") as refused,
    ):
        source.acquire(119, "hres")
    context = refused.value.bulk_status_acquisition
    assert context["operation"] == "bulk-status-archive"
    assert context["requestCount"] == 1
    assert context["budget"]["max_bytes"] == BUDGET.max_bytes
    assert refused.value.capture.body == ZIP
    assert refused.value.refused_response.stage == "source-validation"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_requests": 0},
        {"max_bytes": 0},
        {"max_bytes": 512 * 1024 * 1024},
        {"max_entries": 0},
        {"max_entry_bytes": 64 * 1024 * 1024},
        {"max_total_bytes": 4 * 1024 * 1024 * 1024},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ],
)
def test_budget_bounds_are_checked_before_any_request(kwargs):
    fields = {"max_requests": 2, "max_bytes": 4 * 1024 * 1024, "timeout_seconds": 7, "min_request_interval_seconds": 0}
    with pytest.raises(ValueError):
        BulkStatusBudget(**{**fields, **kwargs})
    with pytest.raises(TypeError, match="BulkStatusBudget"):
        BulkStatusAcquirer(budget=fields)


@pytest.mark.integration
def test_live_hres_archive_parses_at_least_what_was_measured():
    """The 119th H.Res. folder on 2026-09-19: 1,566 members, 3,934,575 zip bytes, none refused."""
    budget = BulkStatusBudget(3, 64 * 1024 * 1024, 120, 1)
    with BulkStatusAcquirer(budget=budget) as source:
        result = source.acquire(119, "hres")
    assert result.capture.requested_url == URL and result.capture.resolved_url == URL
    assert not httpx.URL(result.capture.requested_url).query
    assert result.capture.status_code == 200
    assert (result.capture.content_type or "").split(";")[0].strip() == "application/zip"
    assert result.capture.byte_size >= 3_934_575
    assert len(result.archive.members) >= 1566
    assert result.archive.refused_count == 0
    assert result.archive.parsed_count == len(result.archive.members)
    assert all(member.identity is not None for member in result.archive.members)
