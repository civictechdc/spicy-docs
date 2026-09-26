"""One BILLS folder: its listing, then its zip read once for the printings a caller keeps.

The folder under test is the publisher's own 114th S.J.Res. session-2 zip and
listing, complete and unchanged (`tests/fixtures/govinfo_bills/README.md`);
the refusal cases rebuild that zip here with one member changed, so every byte
of each archive stays reviewable.
"""

import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.bill_acquisition import BillSourceUnavailableError
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError
from spicy_docs.sources.congress.bulk_bills import (
    BULK_BILLS_FLOOR,
    BulkBillsAcquirer,
    bulk_bills_listing_locator,
    bulk_bills_locator,
    read_bulk_bills_archive,
    read_bulk_bills_listing,
)
from spicy_docs.sources.congress.bulk_status import BulkArchiveBudget, BulkStatusBudget, zip_entry_unchanged
from spicy_docs.transport import retry
from spicy_docs.transport.captured import CapturedBodyResponse
from tests.source_fixtures import archive_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
ZIP = (FIXTURES / "bulk-bills-114-2-sjres.zip").read_bytes()
LISTING = (FIXTURES / "listing-bills-114-2-sjres.json").read_bytes()
URL = "https://www.govinfo.gov/bulkdata/BILLS/114/2/sjres/BILLS-114-2-sjres.zip"
LISTING_URL = "https://www.govinfo.gov/bulkdata/json/BILLS/114/2/sjres"
OBSERVED_AT = "2026-09-26T12:44:18Z"
BUDGET = BulkArchiveBudget(2, 4 * 1024 * 1024, 7, 0)


def members() -> list[tuple[str, bytes]]:
    """The publisher zip's members, in its own order."""
    with zipfile.ZipFile(BytesIO(ZIP)) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def listing():
    return read_bulk_bills_listing(LISTING, congress=114, session=2, bill_type="sjres")


def zip_capture(body: bytes = ZIP, url: str = URL) -> CapturedBodyResponse:
    """A retained zip response, as the acquirer would have captured it."""
    return CapturedBodyResponse(
        requested_url=url,
        resolved_url=url,
        status_code=200,
        content_type="application/zip",
        observed_at=OBSERVED_AT,
        body=body,
    )


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def response(body: bytes, content_type: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_locators_are_the_keyless_publisher_folder_and_refuse_anything_else():
    """One zip and one listing per Congress, session and type, spelled as the publisher does."""
    assert bulk_bills_locator(114, 2, "sjres") == URL
    assert bulk_bills_listing_locator(114, 2, "sjres") == LISTING_URL
    assert BULK_BILLS_FLOOR == 113
    for congress, session, bill_type in [(114, 3, "sjres"), (114, 0, "sjres"), (114, 2, "SJRES"), (0, 1, "hr")]:
        with pytest.raises(BillSourceError):
            bulk_bills_locator(congress, session, bill_type)
        with pytest.raises(BillSourceError):
            bulk_bills_listing_locator(congress, session, bill_type)


def test_the_listing_names_every_printing_and_the_folder_zip():
    """Sixteen printings by package id, and the zip entry the unchanged skip compares."""
    folder = listing()
    assert (folder.congress, folder.session, folder.bill_type) == (114, 2, "sjres")
    assert len(folder.entries) == 17
    assert sorted(folder.members) == sorted(name.removesuffix(".xml") for name, _ in members())
    assert folder.members["BILLS-114sjres22enr"].size == 2874
    assert (folder.zip_entry.name, folder.zip_entry.link, folder.zip_entry.size) == (
        "BILLS-114-2-sjres.zip",
        URL,
        31874,
    )
    assert zip_entry_unchanged(folder.zip_entry, folder.zip_entry)


def test_a_listing_entry_from_another_folder_refuses_the_whole_listing():
    """The BILLSTATUS listing reader, shared: another session's link is not this folder's."""
    value = json.loads(LISTING)
    value["files"][0]["link"] = value["files"][0]["link"].replace("/114/2/", "/114/1/")
    with pytest.raises(BillSourceError, match="another Congress or bill type"):
        read_bulk_bills_listing(json.dumps(value).encode(), congress=114, session=2, bill_type="sjres")
    with pytest.raises(BillSourceError, match="another Congress or bill type"):
        read_bulk_bills_listing(LISTING, congress=114, session=1, bill_type="sjres")
    value = json.loads(LISTING)
    value["files"] = [entry for entry in value["files"] if not entry["name"].endswith(".zip")]
    with pytest.raises(BillSourceError, match="no zip entry"):
        read_bulk_bills_listing(json.dumps(value).encode(), congress=114, session=2, bill_type="sjres")


def test_every_member_is_read_once_with_the_zip_as_its_request_and_its_own_digest():
    """Each printing's body names the zip it was read from and carries the member's own bytes and digest."""
    archive = read_bulk_bills_archive(zip_capture(), listing=listing())
    expected = members()
    assert (archive.read_count, archive.refused_count, archive.skipped_count) == (16, 0, 0)
    assert [member.name for member in archive.members] == [name for name, _ in expected]
    for member, (name, data) in zip(archive.members, expected, strict=True):
        assert member.package_id == name.removesuffix(".xml")
        number = re.fullmatch(r"BILLS-114sjres([0-9]+)[a-z]+\.xml", name)
        assert number is not None and member.identity == BillIdentity(114, "sjres", int(number[1]))
        assert (member.byte_size, member.sha256) == (len(data), digest(data))
        body = member.body
        assert body is not None
        assert (body.requested_url, body.resolved_url, body.observed_at) == (URL, URL, OBSERVED_AT)
        assert (body.content_type, body.member, body.body) == ("application/xml", name, data)
        assert (body.byte_size, body.sha256) == (len(data), digest(data))


def test_only_kept_members_are_read_and_the_rest_are_counted():
    """A steady-state run keeps the printings it came for; the others are passed over, never decompressed."""
    wanted = {"BILLS-114sjres22enr", "BILLS-114sjres41is"}
    archive = read_bulk_bills_archive(zip_capture(), listing=listing(), keep=wanted.__contains__)
    assert {member.package_id for member in archive.members} == wanted
    assert (archive.read_count, archive.skipped_count) == (2, 14)


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda name, data: (name.replace("114sjres22", "114sjres99"), data), "not named in the folder listing"),
        (lambda name, data: (name, data + b" "), "size differs from the folder listing"),
        (lambda name, data: (name.replace("114sjres", "113sjres"), data), "another Congress or bill type"),
        (lambda name, data: (name.replace(".xml", ".txt"), data), "does not state a printing"),
    ],
)
def test_a_member_the_listing_or_its_name_does_not_vouch_for_is_one_refused_outcome(change, refusal):
    """One member changed: that member is refused by name, with its digest, and the other fifteen are read."""
    original = members()
    changed = [change(*original[0]), *original[1:]]
    archive = read_bulk_bills_archive(zip_capture(archive_bytes(*changed)), listing=listing())
    first = archive.members[0]
    assert first.body is None and refusal in (first.refusal or "")
    assert first.sha256 == digest(changed[0][1])
    assert (archive.read_count, archive.refused_count) == (15, 1)


def test_a_listing_that_does_not_state_xml_refuses_the_member():
    """The body's content type is the listing's statement, so a listing that states another type refuses it."""
    value = json.loads(LISTING)
    for entry in value["files"]:
        if entry["name"] == "BILLS-114sjres22enr.xml":
            entry["mimeType"] = "application/pdf"
    folder = read_bulk_bills_listing(json.dumps(value).encode(), congress=114, session=2, bill_type="sjres")
    archive = read_bulk_bills_archive(zip_capture(), listing=folder)
    refused = [member for member in archive.members if member.refusal]
    assert [member.package_id for member in refused] == ["BILLS-114sjres22enr"]
    assert "does not state XML" in (refused[0].refusal or "")


def test_a_zip_captured_from_another_folder_is_refused_before_any_member():
    """The capture must be the listed folder's own zip, or its members would be vouched for by the wrong listing."""
    with pytest.raises(BillSourceError, match="not the listed folder's zip"):
        read_bulk_bills_archive(zip_capture(url=URL.replace("/2/", "/1/").replace("-2-", "-1-")), listing=listing())


def test_the_acquirer_lists_then_downloads_only_when_asked():
    """``list_folder`` is one JSON request; ``acquire`` one zip request read against that listing."""
    transport = Transport(response(LISTING, "application/json"), response(ZIP, "application/zip"))
    with BulkBillsAcquirer(budget=BUDGET, transport=transport) as source:
        folder = source.list_folder(114, 2, "sjres")
        assert folder.capture.requested_url == LISTING_URL and folder.request_count == 1
        acquired = source.acquire(folder.listing, keep={"BILLS-114sjres30is"}.__contains__)
    assert [str(call.url) for call in transport.calls] == [LISTING_URL, URL]
    assert transport.calls[0].headers["accept"] == "application/json"
    assert acquired.capture.body == ZIP and acquired.request_count == 1
    assert [member.package_id for member in acquired.archive.members] == ["BILLS-114sjres30is"]


def test_a_missing_folder_or_a_non_zip_answer_is_refused_with_its_capture():
    """A 404 is that folder's absence, not the Congress's; a zip route answering HTML is refused."""
    transport = Transport(response(b"{}", "application/json", 404))
    with BulkBillsAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceUnavailableError):
        source.list_folder(114, 2, "sjres")
    transport = Transport(response(b"<html></html>", "text/html"))
    with BulkBillsAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceError) as error:
        source.acquire(listing())
    assert error.value.__dict__["bulk_bills_acquisition"]["operation"] == "bulk-bills-archive"


def test_the_budget_is_the_bulk_archive_budget_the_status_folders_use():
    """One bound for both collections; the status name stays for its callers."""
    assert BulkStatusBudget is BulkArchiveBudget
    with pytest.raises(TypeError, match="BulkArchiveBudget"):
        BulkBillsAcquirer(budget={"max_requests": 1})


@pytest.mark.integration
def test_live_folder_lists_and_reads_what_was_measured():
    """The 114th S.J.Res. session-2 folder on 2026-09-26: 16 printings in a 31,874-byte zip, none refused."""
    with BulkBillsAcquirer(budget=BulkArchiveBudget(2, 64 * 1024 * 1024, 120, 1)) as source:
        folder = source.list_folder(114, 2, "sjres")
        acquired = source.acquire(folder.listing)
    assert acquired.capture.requested_url == URL and acquired.capture.byte_size >= 31_874
    assert acquired.archive.read_count >= 16 and acquired.archive.refused_count == 0
