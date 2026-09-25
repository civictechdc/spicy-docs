"""FERC eLibrary DownloadPDF and P8 originals: bounded POSTed files, and the pinned FERC vocabularies.

The download route is POST-only (see the module docstring), so the shared
walled-fetch ladder -- whose rungs are all GET -- is not climbed; these tests
script the acquirers' transport instead. The vocabulary tests pin the
publisher's published rosters against the module's own counts and the constants
the readers ship.
"""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.ferc.download import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    MAX_DOWNLOAD_BYTES,
    DownloadAcquisition,
    FercElibraryDownloadAcquirer,
    FercElibraryDownloadBudget,
    FercElibraryDownloadError,
    FercElibraryDownloadRefusedError,
    FercElibraryDownloadUnavailableError,
    pdf_download_body,
    pdf_download_url,
    usable_server_location,
)
from spicy_docs.sources.ferc.elibrary import (
    API,
    RULEMAKING_COMMENT,
    FercElibraryAccessRefusedError,
    FercElibraryError,
    docket_id,
    file_list_url,
    read_file_list,
)
from spicy_docs.sources.ferc.originals import (
    ORIGINAL_DOWNLOAD_URL,
    FercElibraryOriginalAcquirer,
    FercElibraryOriginalError,
    FercElibraryOriginalUnavailableError,
    original_download_body,
)
from spicy_docs.sources.ferc.vocabulary import (
    CLASS_TYPE_PAIRS,
    DOCKET_PREFIXES,
    FERC_CLASS_TYPE_PAIR_COUNT,
    FERC_CLASS_TYPE_PDF_ROW_COUNT,
    FERC_DOCKET_PREFIX_ROW_COUNT,
    SERIAL_DOCKET_PREFIXES,
    docket_prefix_code,
    docket_prefix_status,
    is_documented_class_type,
    require_documented_class_type,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures"
# Real publisher bytes retained for the regulations.gov attachment route; the
# check under test is format, not provenance.
PDF = (FIXTURES / "regulations_gov_attachments" / "FAA-2016-6907-0001-content.pdf").read_bytes()
BUDGET = FercElibraryDownloadBudget(DEFAULT_MAX_DOWNLOAD_BYTES, 7, 0)
ACCESSION = "20251125-3057"
URL = f"{API}/File/DownloadPDF?accesssionNumber={ACCESSION}"
ORIGINAL_ACCESSION = "20240807-5052"
ORIGINAL_ID = "0731EC70-0165-CA3E-91B7-912DB6700000"
ORIGINAL_PDF = (FIXTURES / "ferc" / "original-20240807-5052.pdf").read_bytes()
AKAMAI_BLOCK = (
    b"<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\n"
    b"You don't have permission to access this resource on this server."
)
LOCATION_BODY = b'{"ServerLocation":"svc://assemble"}'


def answer(body, *, status=200, content_type="application/pdf", **headers):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type, **headers})


def scripted(*answers):
    """A transport that records each request and serves, or raises, each queued answer in turn."""
    calls: list[httpx.Request] = []
    queue = iter(answers)

    def handle(request):
        calls.append(request)
        queued = next(queue)
        if isinstance(queued, BaseException):
            raise queued
        return queued

    return httpx.MockTransport(handle), calls


def download(*answers, **options):
    """Acquire ``ACCESSION`` against scripted answers; returns the acquisition and the requests sent."""
    transport, calls = scripted(*answers)
    with FercElibraryDownloadAcquirer(budget=BUDGET, transport=transport) as source:
        return source.acquire(ACCESSION, **options), calls


def refused_download(error_type, *answers):
    """The error a scripted download raises, and the requests sent before it."""
    transport, calls = scripted(*answers)
    with (
        FercElibraryDownloadAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(error_type) as raised,
    ):
        source.acquire(ACCESSION)
    return raised.value, calls


def original_listing(*, changes=None, duplicate=False):
    body = (FIXTURES / "ferc" / "file-list-p8-20240807-5052.json").read_bytes()
    if changes or duplicate:
        value = json.loads(body)
        value["DataList"][0].update(changes or {})
        if duplicate:
            value["DataList"].append(value["DataList"][0])
        body = json.dumps(value).encode()
    url = file_list_url(ORIGINAL_ACCESSION)
    capture = CapturedBodyResponse(url, url, 200, "application/json", "2026-09-25T00:42:12.452322Z", body)
    return read_file_list(capture, accession=ORIGINAL_ACCESSION)


def test_original_download_matches_the_browser_request_and_preserves_the_parent_capture():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200, stream=httpx.ByteStream(ORIGINAL_PDF), headers={"content-type": "application/octet-stream"}
        )

    listing = original_listing()
    browser_body = (FIXTURES / "ferc" / "original-download-browser-request.json").read_bytes()
    assert original_download_body(ORIGINAL_ID) == browser_body
    with FercElibraryOriginalAcquirer(budget=BUDGET, transport=httpx.MockTransport(handle)) as source:
        acquired = source.acquire(listing, file_id=ORIGINAL_ID)
        again = source.acquire(listing, file_id=ORIGINAL_ID)
    assert acquired.capture.body == ORIGINAL_PDF and not acquired.requested_empty
    assert acquired.file_id == ORIGINAL_ID and acquired.accession == ORIGINAL_ACCESSION
    assert acquired.metadata == listing.records[0]
    assert acquired.file_list_sha256 == listing.capture.sha256
    assert acquired.sha256 == "sha256:c7ef927914a7a53d17ed0f3ddf4fc67143bfb91ccbd401bab162929510fc818f"
    assert acquired.request_count == again.request_count == 1
    assert all(request.method == "POST" and str(request.url) == ORIGINAL_DOWNLOAD_URL for request in calls)
    assert all(request.content == browser_body for request in calls)
    assert acquired.capture.method == "POST" and acquired.capture.request_body == browser_body
    assert calls[0].headers["x-applicationid"] == "52f6cc3e-3b73-4b1d-9668-05c32c17bf38"
    assert calls[0].headers["x-sessionid"] == calls[1].headers["x-sessionid"]
    assert calls[0].headers["x-correlationid"] != calls[1].headers["x-correlationid"]


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"Accession_Number": "20240807-5051"}, "different accession"),
        ({"Availability_Mode": "CEII"}, "public availability"),
        ({"File_Size_Num": None}, "byte size"),
        ({"File_Size_Num": True}, "byte size"),
        ({"Orig_File_Name": ""}, "file name"),
        ({"MimeType": None}, "media type"),
    ],
)
def test_original_metadata_must_establish_the_selected_public_file_before_any_request(changes, message):
    def unexpected(_request):
        pytest.fail("invalid metadata must spend no request")

    with (
        FercElibraryOriginalAcquirer(budget=BUDGET, transport=httpx.MockTransport(unexpected)) as source,
        pytest.raises(FercElibraryOriginalError, match=message),
    ):
        source.acquire(original_listing(changes=changes), file_id=ORIGINAL_ID)


def test_original_selection_refuses_undeclared_duplicate_legacy_and_oversized_files_before_requesting():
    def unexpected(_request):
        pytest.fail("invalid selection must spend no request")

    with FercElibraryOriginalAcquirer(budget=BUDGET, transport=httpx.MockTransport(unexpected)) as source:
        with pytest.raises(FercElibraryOriginalError, match="exactly once"):
            source.acquire(original_listing(), file_id="FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
        with pytest.raises(FercElibraryOriginalError, match="exactly once"):
            source.acquire(original_listing(duplicate=True), file_id=ORIGINAL_ID)
        with pytest.raises(FercElibraryOriginalError, match="GUID"):
            source.acquire(original_listing(), file_id="12345")
        with pytest.raises(FercElibraryOriginalError, match="byte bound"):
            source.acquire(original_listing(), file_id=ORIGINAL_ID, max_bytes=1)


@pytest.mark.parametrize(
    "body,media_type,message",
    [
        (ORIGINAL_PDF[:-1], "application/octet-stream", "declared size"),
        (b"!" + ORIGINAL_PDF[1:], "application/octet-stream", "PDF.*magic"),
        (b"<html>challenge</html>", "application/octet-stream", "returned HTML"),
        (ORIGINAL_PDF, "application/json", "Content-Type"),
    ],
    ids=["wrong-size", "wrong-magic", "html-challenge", "wrong-media-type"],
)
def test_original_capture_refuses_wrong_size_format_and_html_with_evidence(body, media_type, message):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": media_type})
    )
    with (
        FercElibraryOriginalAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(FercElibraryOriginalError, match=message) as raised,
    ):
        source.acquire(original_listing(), file_id=ORIGINAL_ID)
    assert raised.value.capture.body == body
    assert raised.value.refused_response.response_bytes == body
    assert raised.value.ferc_elibrary_original_acquisition["fileId"] == ORIGINAL_ID


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_original_http_refusal_keeps_the_body_and_aborts_without_retry(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(b"unavailable"), headers={"content-type": "text/plain"})

    error_type = FercElibraryAccessRefusedError if status in (401, 403) else FercElibraryOriginalUnavailableError
    with (
        FercElibraryOriginalAcquirer(budget=BUDGET, transport=httpx.MockTransport(handle)) as source,
        pytest.raises(error_type) as raised,
    ):
        source.acquire(original_listing(), file_id=ORIGINAL_ID)
    assert len(calls) == 1
    assert raised.value.refused_response.response_bytes == b"unavailable"
    assert raised.value.ferc_elibrary_original_acquisition["requestCount"] == 1


def test_a_declared_empty_original_is_a_requested_empty_observation():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(b""), headers={"content-type": "application/pdf"})
    )
    with FercElibraryOriginalAcquirer(budget=BUDGET, transport=transport) as source:
        acquired = source.acquire(original_listing(changes={"File_Size_Num": 0}), file_id=ORIGINAL_ID)
    assert acquired.requested_empty and acquired.capture.body == b""


def test_the_download_locator_and_body_spell_the_bundle_shape():
    assert pdf_download_url(ACCESSION) == URL
    assert json.loads(pdf_download_body()) == {"serverLocation": ""}
    assert json.loads(pdf_download_body("loc-1")) == {"serverLocation": "loc-1"}


def test_only_a_nonempty_server_location_in_a_400_body_is_usable():
    assert usable_server_location(json.dumps({"ServerLocation": "svc://x"}).encode()) == "svc://x"
    for body in (
        b"",
        b"{}",
        b'{"ServerLocation": ""}',
        b'{"ServerLocation": 7}',
        b"plain error prose",
        b'{"serverLocation": "x"}',
    ):
        assert usable_server_location(body) is None


def test_one_clean_pdf_is_acquired_with_the_spa_headers_and_its_exact_post():
    acquisition, calls = download(answer(PDF, **{"content-length": str(len(PDF))}))
    assert isinstance(acquisition, DownloadAcquisition)
    assert acquisition.capture.body == PDF and acquisition.requested_empty is False
    assert acquisition.capture.method == "POST" and acquisition.capture.request_body == pdf_download_body()
    assert acquisition.request_count == 1 and acquisition.captures == (acquisition.capture,)
    assert acquisition.accession == ACCESSION and acquisition.budget is BUDGET
    (request,) = calls
    assert request.method == "POST" and str(request.url) == URL and request.read() == pdf_download_body()
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-applicationid"] == "52f6cc3e-3b73-4b1d-9668-05c32c17bf38"
    assert request.headers["x-sessionid"] and request.headers["x-correlationid"]
    assert request.headers["user-agent"].startswith("Mozilla/5.0")


def test_a_400_naming_a_server_location_gets_exactly_one_follow_up_and_both_posts_are_retained():
    acquisition, calls = download(answer(LOCATION_BODY, status=400, content_type="application/json"), answer(PDF))
    assert acquisition.request_count == 2 and acquisition.capture.body == PDF
    assert [capture.status_code for capture in acquisition.captures] == [400, 200]
    assert acquisition.captures[-1] is acquisition.capture
    assert [capture.method for capture in acquisition.captures] == ["POST", "POST"]
    # The retained request bodies are the bytes the transport actually received.
    assert [capture.request_body for capture in acquisition.captures] == [request.content for request in calls]
    assert [json.loads(request.content) for request in calls] == [
        {"serverLocation": ""},
        {"serverLocation": "svc://assemble"},
    ]
    assert calls[0].headers["x-sessionid"] == calls[1].headers["x-sessionid"]
    assert calls[0].headers["x-correlationid"] != calls[1].headers["x-correlationid"]


def test_a_400_that_names_no_server_location_is_a_publisher_refusal_with_evidence():
    body = b'{"Code": "2", "FileName": ["TOTAL_FILE_SIZE_EXCEEDED_MAX"]}'
    error, calls = refused_download(
        FercElibraryDownloadRefusedError, answer(body, status=400, content_type="application/json")
    )
    assert isinstance(error, CredentialRefusedError)
    assert error.refusal_kind == "publisher-refused"
    assert "not an observation that the file is absent" in str(error)
    assert error.refused_response.response_bytes == body
    assert error.ferc_elibrary_download_acquisition["accession"] == ACCESSION
    assert error.ferc_elibrary_download_acquisition["requestCount"] == 1
    assert [capture.body for capture in error.captures] == [body]
    assert len(calls) == 1


@pytest.mark.parametrize("status", [200, 403, 401])
def test_a_wall_marked_answer_is_a_client_rejection_never_absence(status):
    error, _ = refused_download(
        FercElibraryDownloadRefusedError, answer(AKAMAI_BLOCK, status=status, content_type="text/html")
    )
    assert error.refusal_kind == "client-rejected" and isinstance(error, CredentialRefusedError)
    assert error.refused_response.response_bytes == AKAMAI_BLOCK
    assert error.ferc_elibrary_download_acquisition["accession"] == ACCESSION


def test_a_markerless_401_is_a_publisher_refusal():
    error, _ = refused_download(FercElibraryDownloadRefusedError, answer(b"", status=401, content_type="text/html"))
    assert error.refusal_kind == "publisher-refused"


def test_a_redirect_answer_is_a_named_refusal_not_a_followed_one():
    error, calls = refused_download(
        FercElibraryDownloadRefusedError,
        answer(b"<html>moved</html>", status=302, content_type="text/html", location="https://other.gov/x"),
    )
    assert error.refusal_kind == "redirected" and len(calls) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_only_404_and_410_say_the_exact_accession_has_nothing(status):
    error, _ = refused_download(
        FercElibraryDownloadUnavailableError, answer(b"", status=status, content_type="application/json")
    )
    assert error.capture.status_code == status


def test_a_requested_empty_answer_is_recorded_not_skipped():
    acquisition, _ = download(answer(b""))
    assert acquisition.requested_empty is True and acquisition.capture.body == b""


@pytest.mark.parametrize(
    "body,content_type,message",
    [
        (b"PK\x03\x04not a pdf", "application/pdf", "does not begin with the %PDF- magic"),
        (b"%PDF-1.4 cut off without a trailer", "application/pdf", "does not end with a PDF trailer"),
        (PDF, "text/html", "not a PDF download type"),
        (PDF, "application/json", "not a PDF download type"),
    ],
)
def test_magic_and_media_type_mismatches_name_the_answer_that_lied(body, content_type, message):
    error, _ = refused_download(FercElibraryDownloadError, answer(body, content_type=content_type))
    assert message in str(error)
    assert error.refused_response.response_bytes == body
    assert error.ferc_elibrary_download_acquisition["accession"] == ACCESSION


def test_follow_up_transport_failure_keeps_the_initial_response_and_attempt_count():
    error, calls = refused_download(
        FercElibraryDownloadError,
        answer(LOCATION_BODY, status=400, content_type="application/json"),
        httpx.ConnectError("connection failed"),
    )
    assert "transport failed" in str(error)
    assert [capture.body for capture in error.captures] == [LOCATION_BODY]
    assert error.captures[0].request_body == calls[0].content
    assert error.ferc_elibrary_download_acquisition["requestCount"] == 2
    assert not hasattr(error, "capture")  # No response was received for the failed POST.


def test_configuration_is_explicit_and_bad_input_spends_no_request():
    transport, calls = scripted()
    with FercElibraryDownloadAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
            source.acquire(ACCESSION, max_bytes="16")
        with pytest.raises(FercElibraryError, match="accession must be"):
            source.acquire("not-an-accession")
        with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
            source.acquire(ACCESSION, max_bytes=0)
    assert calls == []
    with pytest.raises(ValueError):
        FercElibraryDownloadBudget(max_bytes=MAX_DOWNLOAD_BYTES + 1, timeout_seconds=7, min_request_interval_seconds=0)
    with pytest.raises(ValueError):
        FercElibraryDownloadBudget(
            max_bytes=DEFAULT_MAX_DOWNLOAD_BYTES, timeout_seconds=0, min_request_interval_seconds=0
        )
    with pytest.raises(TypeError):
        FercElibraryDownloadAcquirer(budget=(DEFAULT_MAX_DOWNLOAD_BYTES, 7, 0))


def test_the_vocabulary_pins_match_the_published_row_counts():
    assert len(DOCKET_PREFIXES) == FERC_DOCKET_PREFIX_ROW_COUNT == 95
    assert len(CLASS_TYPE_PAIRS) == FERC_CLASS_TYPE_PAIR_COUNT == 230
    assert FERC_CLASS_TYPE_PAIR_COUNT < FERC_CLASS_TYPE_PDF_ROW_COUNT == 235, (
        "repeated pairs collapse; the pin states both"
    )


def test_the_published_docket_prefix_scheme_is_what_the_identity_grammar_keeps():
    assert docket_prefix_code("RM24-5") == "RM" and docket_prefix_code("p-1234-000") == "P"
    assert docket_prefix_status("RM") == "active" and docket_prefix_status("P") == "active"
    assert docket_prefix_status("G-") == "discontinued"
    assert docket_prefix_status("QQ") is None
    assert len(DOCKET_PREFIXES) == len({prefix for prefix, _status in DOCKET_PREFIXES})


def test_the_shipped_comment_selection_is_a_documented_class_type_pair():
    assert is_documented_class_type(*RULEMAKING_COMMENT)
    require_documented_class_type(*RULEMAKING_COMMENT)
    assert is_documented_class_type("Comments/Protest", "Settlement Comment")
    assert not is_documented_class_type("Comments/Protest", "Not a Published Type")
    assert not is_documented_class_type("Not a Class", "Rulemaking Comment")
    with pytest.raises(ValueError, match="not a documented FERC eLibrary class/type pair"):
        require_documented_class_type("Not a Class", "Rulemaking Comment")
    assert len(CLASS_TYPE_PAIRS) == len(set(CLASS_TYPE_PAIRS))


def test_serial_numbered_docket_spellings_are_active_roster_prefixes_the_grammar_admits():
    """``P-`` and ``ID-`` dockets carry a serial number, not a fiscal year; each prefix is in the pinned roster."""
    assert all(docket_prefix_status(prefix) == "active" for prefix in SERIAL_DOCKET_PREFIXES)
    for prefix in SERIAL_DOCKET_PREFIXES:
        assert docket_id(f"{prefix.lower()}-10800-000") == f"{prefix}-10800-000"
