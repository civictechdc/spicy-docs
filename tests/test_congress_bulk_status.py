"""One BILLSTATUS folder zip: every member proved or refused, and the bounds that refuse the zip.

The archive under test is built here from complete, unchanged members of the
119th H.Res. zip (`tests/fixtures/govinfo_bills/README.md`), plus two members
that cannot be what their names claim. Building it here keeps every byte of the
archive reviewable; the publisher's own zip is the live test below.
"""

import dataclasses
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.bill_acquisition import BillSourceUnavailableError
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError
from spicy_docs.sources.congress.bulk_status import (
    BulkStatusAcquirer,
    BulkStatusBudget,
    bulk_listing_locator,
    bulk_status_locator,
    read_bulk_listing,
    read_bulk_status_archive,
)
from spicy_docs.transport import retry
from tests.source_fixtures import archive_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
PLAIN = (FIXTURES / "status-119hres1376.xml").read_bytes()
CDATA = (FIXTURES / "status-119hres10.xml").read_bytes()
UNTEXTED_ACTION = (FIXTURES / "status-119hres214.xml").read_bytes()
LISTING = (FIXTURES / "listing-119hres.json").read_bytes()
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
LISTING_URL = "https://www.govinfo.gov/bulkdata/json/BILLSTATUS/119/hres"
BUDGET = BulkStatusBudget(2, 4 * 1024 * 1024, 7, 0)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def response(body=ZIP, status=200, *, content_type="application/zip"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


def listing_response(body=LISTING, status=200, *, content_type="application/json"):
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
    assert wrapped.status.summaries[0].text.startswith("<p><strong>House Endeavor")

    assert plain.status.summaries[0].text.startswith("<p>This resolution recognizes")
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
        # A name whose digits outrun int()'s own limit must still be one
        # refused member, not an untyped ValueError that ends the archive.
        (f"BILLSTATUS-119hres{'9' * 4301}.xml", "does not state a bill identity"),
        (f"BILLSTATUS-{'9' * 4301}hres10.xml", "does not state a bill identity"),
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


def test_bulk_listing_locator_is_the_keyless_publisher_json_route_and_refuses_anything_else():
    assert bulk_listing_locator(119, "hres") == LISTING_URL
    assert bulk_listing_locator(108, "s") == "https://www.govinfo.gov/bulkdata/json/BILLSTATUS/108/s"
    for congress, bill_type in [(119, "HRES"), (119, "hres/../hr"), (119, "bill"), (0, "hres"), (True, "hres")]:
        with pytest.raises(BillSourceError):
            bulk_listing_locator(congress, bill_type)


def test_read_bulk_listing_parses_every_field_and_proves_the_zip_entry():
    listing = read_bulk_listing(LISTING, congress=119, bill_type="hres")
    assert (listing.congress, listing.bill_type) == (119, "hres")
    assert len(listing.entries) == 4
    # Measured 2026-09-19: this route answers only {"files": [...]}, no own stamp.
    assert listing.folder_modified is None

    zip_entry = listing.zip_entry
    assert (zip_entry.name, zip_entry.display_label, zip_entry.just_file_name) == (
        "BILLSTATUS-119-hres.zip",
        "BILLSTATUS-119-hres.zip",
        "BILLSTATUS-119-hres.zip",
    )
    assert zip_entry.link == URL
    assert zip_entry.folder is False
    assert (zip_entry.mime_type, zip_entry.file_extension, zip_entry.formatted_size) == (
        "application/zip",
        "zip",
        "3.8 MB",
    )
    assert zip_entry.formatted_last_modified_time == "18-Sep-2026 20:26"
    assert zip_entry.modified_at == datetime(2026, 9, 18, 20, 26, tzinfo=UTC)
    assert zip_entry.size == 3934575

    xml_entry = next(entry for entry in listing.entries if entry.name == "BILLSTATUS-119hres10.xml")
    assert (xml_entry.size, xml_entry.mime_type, xml_entry.file_extension) == (8109, "application/xml", "xml")
    assert xml_entry.link == "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hres/BILLSTATUS-119hres10.xml"
    assert xml_entry.modified_at == datetime(2025, 1, 30, 15, 7, tzinfo=UTC)


def test_a_listing_entry_that_belongs_to_another_folder_refuses_the_whole_listing():
    body = json.loads(LISTING.decode())
    body["files"][0]["link"] = body["files"][0]["link"].replace("/119/hres/", "/119/hr/")
    with pytest.raises(BillSourceError, match="belongs to another Congress or bill type"):
        read_bulk_listing(json.dumps(body).encode(), congress=119, bill_type="hres")


def test_a_listing_with_no_zip_entry_for_the_folder_refuses_by_name():
    """Empty success is not absence: {"files": [...]} with no zip row still refuses."""
    body = json.loads(LISTING.decode())
    body["files"] = [entry for entry in body["files"] if not entry["name"].endswith(".zip")]
    with pytest.raises(BillSourceError, match="has no zip entry"):
        read_bulk_listing(json.dumps(body).encode(), congress=119, bill_type="hres")


def test_list_archives_captures_the_listing_with_the_json_accept_header():
    transport = Transport(listing_response())
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.list_archives(119, "hres")
    assert result.capture.body == LISTING
    assert result.capture.requested_url == LISTING_URL and result.capture.resolved_url == LISTING_URL
    assert result.capture.content_type == "application/json"
    assert transport.calls[0].headers.get("accept") == "application/json"
    assert (result.listing.congress, result.listing.bill_type) == (119, "hres")
    assert result.listing.zip_entry.size == 3934575
    assert (result.request_count, result.budget) == (1, BUDGET)


def test_acquire_skips_the_zip_download_when_the_listing_proves_it_is_unchanged():
    seen = read_bulk_listing(LISTING, congress=119, bill_type="hres").zip_entry
    transport = Transport(listing_response())
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(119, "hres", unchanged_since=seen)
    # Only the listing was requested; a StopIteration on a second call would have
    # meant the zip was asked for too.
    assert len(transport.calls) == 1
    assert str(transport.calls[0].url) == LISTING_URL
    assert result.skipped_unchanged is True
    assert result.archive is None
    assert result.capture is None
    assert result.listing_capture is not None and result.listing_capture.body == LISTING
    assert result.listing_entry == seen


def test_acquire_downloads_the_zip_when_the_listing_shows_it_changed():
    seen = read_bulk_listing(LISTING, congress=119, bill_type="hres").zip_entry
    stale = dataclasses.replace(seen, size=seen.size - 1)
    transport = Transport(listing_response(), response())
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(119, "hres", unchanged_since=stale)
    assert len(transport.calls) == 2
    assert str(transport.calls[0].url) == LISTING_URL
    assert str(transport.calls[1].url) == URL
    assert result.skipped_unchanged is False
    assert result.archive is not None
    assert result.capture.body == ZIP
    assert result.listing_capture is not None and result.listing_capture.body == LISTING
    assert result.listing_entry == seen
    # The listing's own capture must not have reset the request budget: both
    # requests this call made are counted, not just the zip's.
    assert result.request_count == 2


def test_acquire_downloads_the_zip_when_only_modified_at_changed():
    """Size alone agreeing must not skip: modified_at changing is enough to mean "changed"."""
    seen = read_bulk_listing(LISTING, congress=119, bill_type="hres").zip_entry
    stale = dataclasses.replace(seen, modified_at=seen.modified_at.replace(year=seen.modified_at.year - 1))
    transport = Transport(listing_response(), response())
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(119, "hres", unchanged_since=stale)
    assert len(transport.calls) == 2
    assert result.skipped_unchanged is False
    assert result.archive is not None and result.capture.body == ZIP


def test_unchanged_since_naming_a_different_file_refuses_rather_than_risk_a_false_skip():
    seen = read_bulk_listing(LISTING, congress=119, bill_type="hres").zip_entry
    other_folder = dataclasses.replace(
        seen,
        name="BILLSTATUS-119-hr.zip",
        link="https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119-hr.zip",
    )
    transport = Transport(listing_response())
    with (
        BulkStatusAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(BillSourceError, match="names a different file"),
    ):
        source.acquire(119, "hres", unchanged_since=other_folder)
    # Only the listing was read; the mismatch is caught before any zip request.
    assert len(transport.calls) == 1
    assert str(transport.calls[0].url) == LISTING_URL


def test_a_listing_that_already_spent_the_request_budget_refuses_the_zip_rather_than_grant_a_second_budget():
    seen = read_bulk_listing(LISTING, congress=119, bill_type="hres").zip_entry
    stale = dataclasses.replace(seen, size=seen.size - 1)
    one_request = BulkStatusBudget(1, 4 * 1024 * 1024, 7, 0)
    transport = Transport(listing_response())
    with (
        BulkStatusAcquirer(budget=one_request, transport=transport) as source,
        pytest.raises(BillSourceError, match="exhausted its total request budget"),
    ):
        source.acquire(119, "hres", unchanged_since=stale)
    # The listing consumed the whole budget; the zip must never have been requested.
    assert len(transport.calls) == 1
    assert str(transport.calls[0].url) == LISTING_URL


def test_acquire_without_unchanged_since_never_reads_the_listing():
    transport = Transport(response())
    with BulkStatusAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(119, "hres")
    assert len(transport.calls) == 1
    assert str(transport.calls[0].url) == URL
    assert result.skipped_unchanged is False
    assert (result.listing_capture, result.listing_entry) == (None, None)


def test_unchanged_since_must_be_a_bulk_listing_entry():
    with (
        BulkStatusAcquirer(budget=BUDGET, transport=Transport()) as source,
        pytest.raises(TypeError, match="BulkListingEntry"),
    ):
        source.acquire(119, "hres", unchanged_since="not-an-entry")


@pytest.mark.integration
def test_live_hres_listing_states_the_zip_entry_the_archive_capture_also_names():
    """The 119th H.Res. folder listing on 2026-09-19: at least the 1,566 members plus the zip."""
    budget = BulkStatusBudget(3, 64 * 1024 * 1024, 120, 1)
    with BulkStatusAcquirer(budget=budget) as source:
        result = source.list_archives(119, "hres")
    assert result.capture.requested_url == LISTING_URL and result.capture.resolved_url == LISTING_URL
    assert not httpx.URL(result.capture.requested_url).query
    assert result.capture.status_code == 200
    assert (result.capture.content_type or "").split(";")[0].strip() == "application/json"
    assert len(result.listing.entries) >= 1567
    zip_entry = result.listing.zip_entry
    assert zip_entry.name == "BILLSTATUS-119-hres.zip"
    assert zip_entry.link == URL
    assert zip_entry.size >= 3_934_575
    assert zip_entry.modified_at.tzinfo is UTC
