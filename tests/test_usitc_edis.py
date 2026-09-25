"""USITC EDIS `/data` XML routes: one pilot investigation read end to end, refusals and evidence retained.

The keyless web service answers ``<results>`` pages of at most 100 rows
under ``pageNumber``, with an empty page beyond the last row, and notifies
new documents through an RSS feed. Earlier live probes reached the host's
Akamai wall; later direct probes reached the download authentication
boundary. The acquirer therefore takes any transport, which also carries the
attachment-PDF ladder's DIRECT rung; the ladder's proxies resolve without a
credential unless a test supplies one, so no test reaches a provider. With a
download token the route makes one credentialed request (direct, or explicit
Zyte selection) on its own client, mocked at the HTTPX or provider seam.
All assert the exact URLs, the walk's ends and refusals, and the reader's
``last_keys``/``failed_keys`` semantics for one pilot investigation
(337-3673 Violation, from the retained captures).
"""

import base64
import hashlib
import io
import json
import traceback
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources import walled_fetch as ladder
from spicy_docs.sources import zyte as zyte_source
from spicy_docs.sources.usitc_edis import (
    PAGE_SIZE,
    EdisAcquirer,
    EdisBudget,
    UsitcEdisReader,
    UsitcEdisSourceError,
    UsitcEdisUnavailableError,
    attachment_download_locator,
    attachment_download_url,
    attachment_url,
    check_edis_data_url,
    document_list_url,
    document_url,
    investigation_url,
    parse_attachments,
    parse_documents,
    parse_edis_feed,
    parse_investigations,
    read_attachment_pdf,
)
from spicy_docs.sources.usitc_edis import api as edis_api
from spicy_docs.sources.usitc_edis import credentialed as edis_credentialed
from spicy_docs.sources.usitc_edis.reader import attachment_record_dict
from spicy_docs.sources.walled_fetch import Transport as LadderTransport
from spicy_docs.sources.walled_fetch import WalledFetchError, WalledFetchResult
from spicy_docs.sources.zyte import ZyteHttpFetcher
from spicy_docs.transport import retry
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "usitc_edis"
INVESTIGATION_731 = (FIXTURES / "investigation-731-1103.xml").read_bytes()
INVESTIGATIONS_ACTIVE = (FIXTURES / "investigations-active-2019.xml").read_bytes()
DOCUMENTS_337_3673 = (FIXTURES / "documents-337-3673-2023.xml").read_bytes()
DOCUMENTS_337_1145 = (FIXTURES / "documents-337-1145-violation.xml").read_bytes()
DOCUMENT_894762 = (FIXTURES / "document-894762.xml").read_bytes()
#: Three whole rows of the live answer to investigationNumber=337-145 (a partial number) on 2026-09-25.
DOCUMENTS_337_145_PREFIX = (FIXTURES / "documents-337-145-prefix.xml").read_bytes()
ATTACHMENT_111112 = (FIXTURES / "attachment-111112.xml").read_bytes()
ATTACHMENT_EMPTY_DOWNLOAD = (FIXTURES / "attachment-880936-empty-download.xml").read_bytes()
FEED_2022 = (FIXTURES / "feed-2022-05-27.xml").read_bytes()

EMPTY_INVESTIGATIONS = b"<results><investigations></investigations></results>"
EMPTY_DOCUMENTS = b"<results><documents></documents></results>"
DOWNLOAD_URL = "https://edis.usitc.gov/data/download/111112/111112"
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
FIXED_INSTANT = datetime(2026, 9, 25, tzinfo=UTC)

BUDGET = EdisBudget(
    max_requests=8,
    max_page_bytes=256 * 1024,
    max_download_bytes=1024 * 1024,
    timeout_seconds=7.0,
    min_request_interval_seconds=0.0,
)

#: The pilot investigation's listing row, adapted from the publisher's own
#: investigation row spelling in the retained 337 captures.
INVESTIGATION_337_3673 = (
    b"<results><investigations><investigation>"
    b"<investigationNumber>337-3673</investigationNumber>"
    b"<investigationPhase>Violation</investigationPhase>"
    b"<investigationStatus>Preinstitution</investigationStatus>"
    b"<investigationTitle>Wi-Fi Routers, Wi-Fi Devices, Mesh Wi-Fi Network Devices, and Hardware and Software "
    b"Components Thereof; Inv. No. 337-TA-3673 (Violation)</investigationTitle>"
    b"<investigationType>Sec 337</investigationType>"
    b"<docketNumber/>"
    b"<documentListUri>https://edis.usitc.gov/data/document?investigationNumber=337-3673"
    b"&amp;investigationPhase=Violation</documentListUri>"
    b"</investigation></investigations></results>"
)


def attachment_page(document_id: int) -> bytes:
    """One attachment row in the publisher's spelling, its ``documentId`` set to the requested document."""
    return (
        b"<results><attachments><attachment>"
        b"<id>111112</id>" + f"<documentId>{document_id}</documentId>".encode() + b"<title>Exhibit, Post-Trial</title>"
        b"<fileSize>304508</fileSize>"
        b"<pageCount/>"
        b"<createDate>2002/10/04 00:00:00</createDate>"
        b"<lastModifiedDate>2011/08/21 09:31:09</lastModifiedDate>"
        b"<downloadUri>https://edis.usitc.gov/data/download/111112/111112</downloadUri>"
        b"</attachment></attachments></results>"
    )


def xml_response(body: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "application/xml"})


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves one response per exact URL."""

    def __init__(self, routes: dict[str, httpx.Response]):
        self.routes = routes
        self.calls: list[httpx.Request] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.routes.get(str(request.url), xml_response(b"<results/>", status=404))


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)
    monkeypatch.setattr(retry.time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def no_ladder_providers(monkeypatch):
    """The ladder's proxies resolve without a credential unless a test supplies one: no test reaches a provider."""
    monkeypatch.setattr(
        ladder.ProxyFetchers,
        "from_environment",
        classmethod(lambda cls: cls("no Zyte credential in tests", "no Firecrawl credential in tests")),
    )


def test_url_builders_spell_the_routes_and_refuse_bad_inputs():
    assert investigation_url() == "https://edis.usitc.gov/data/investigation?pageNumber=1"
    assert investigation_url(number="731-1103", phase="Final") == (
        "https://edis.usitc.gov/data/investigation/731-1103/Final?pageNumber=1"
    )
    assert investigation_url(status="Active", investigation_type="Import Injury", page=3) == (
        "https://edis.usitc.gov/data/investigation?investigationType=Import+Injury"
        "&investigationStatus=Active&pageNumber=3"
    )
    assert document_list_url(investigation_number="337-1145", investigation_phase="Violation") == (
        "https://edis.usitc.gov/data/document?investigationNumber=337-1145&investigationPhase=Violation&pageNumber=1"
    )
    assert document_list_url(document_type="Complaint", firm_org="Latham & Watkins LLP", security_level="Public") == (
        "https://edis.usitc.gov/data/document?documentType=Complaint&firmOrg=Latham+%26+Watkins+LLP"
        "&securityLevel=Public&pageNumber=1"
    )
    assert attachment_url(793615) == "https://edis.usitc.gov/data/attachment/793615"
    assert document_url(894762) == "https://edis.usitc.gov/data/document/894762"
    assert attachment_download_url(111112, 111112) == DOWNLOAD_URL
    for kwargs in ({"number": ""}, {"number": " 731-1103 "}, {"page": 0}, {"page": True}, {"phase": "x" * 257}):
        with pytest.raises(UsitcEdisSourceError):
            investigation_url(**kwargs)
    with pytest.raises(UsitcEdisSourceError):
        attachment_url(0)
    with pytest.raises(UsitcEdisSourceError, match="phase requires an investigation number"):
        investigation_url(phase="Final")
    for bad_id in (0, -1, True, "894762", 10**12 + 1):
        with pytest.raises(UsitcEdisSourceError, match="positive integer"):
            document_url(bad_id)


def test_locator_grammar_accepts_publisher_spellings_and_refuses_the_rest():
    stated = "https://edis.usitc.gov/data/document?investigationNumber=337-3673&investigationPhase=Violation"
    assert check_edis_data_url(stated) == stated
    assert check_edis_data_url("https://edis.usitc.gov/data/attachment/793615") is not None
    for bad in (
        "http://edis.usitc.gov/data/document",
        "https://edis.usitc.gov/external/search/document/770876",
        "https://evil.example/data/document",
        "https://edis.usitc.gov/data/document#frag",
        "https://user@edis.usitc.gov/data/document",
        "https://edis.usitc.gov/data/document?api_key=secret",
        "https://edis.usitc.gov/data/document?token=abc",
    ):
        with pytest.raises(UsitcEdisSourceError):
            check_edis_data_url(bad)


def test_parse_investigations_keeps_phases_distinct_and_empty_fields_absent():
    rows = parse_investigations(INVESTIGATION_731)
    assert [row.identity for row in rows] == [
        ("731-1103", "Final"),
        ("731-1103", "Prelim"),
        ("731-1103", "Review"),
        ("731-1103", "Review2"),
    ]
    final = rows[0]
    assert final.status == "Active" and final.type == "Import Injury"
    assert final.docket_number is None  # the publisher's empty <docketNumber/>
    assert final.document_list_url == (
        "https://edis.usitc.gov/data/document?investigationNumber=731-1103&investigationPhase=Final"
    )
    assert parse_investigations(EMPTY_INVESTIGATIONS) == ()


def test_parse_refusals_keep_a_bad_page_from_reading_as_a_listing():
    with pytest.raises(UsitcEdisSourceError, match="root is not"):
        parse_investigations(b"<investigations></investigations>")
    with pytest.raises(UsitcEdisSourceError, match="something other than"):
        parse_investigations(b"<results><investigations><other/></investigations></results>")
    with pytest.raises(UsitcEdisSourceError, match="omitted its investigationNumber"):
        parse_investigations(
            b"<results><investigations><investigation><investigationPhase>Final</investigationPhase>"
            b"</investigation></investigations></results>"
        )


def test_parse_documents_keeps_publisher_spellings_across_capture_eras():
    recent = parse_documents(DOCUMENTS_337_3673)
    assert [row.id for row in recent] == [793615, 793596, 793595]
    first = recent[0]
    assert first.document_type == "Complaint"
    assert first.document_title == "Appendices A - L"
    assert first.firm_organization == "Latham & Watkins LLP"
    assert first.filed_by == "Kevin C. Wheeler"
    assert first.on_behalf_of == "Netgear Inc."
    assert first.document_date == "2023/04/03 00:00:00"
    assert first.official_received_date == "2023/04/03 16:43:00"
    assert first.action_jacket_control_number is None  # the publisher's empty element
    assert first.security_level == "Public" and recent[1].security_level == "Confidential"
    assert first.attachment_list_url == "https://edis.usitc.gov/data/attachment/793615"
    older = parse_documents(DOCUMENTS_337_1145)
    assert older[0].document_date == "2020/07/09 00:00:00"
    assert older[0].firm_organization == "Foster, Murphy, Altman & Nickel, PC"
    assert parse_documents(EMPTY_DOCUMENTS) == ()


def test_parse_attachments_reads_one_document_and_enforces_the_stated_document():
    rows = parse_attachments(ATTACHMENT_111112, document_id=111112)
    assert len(rows) == 1
    row = rows[0]
    assert (row.id, row.document_id) == (111112, 111112)
    assert row.file_size == 304508 and row.page_count is None  # the publisher's empty <pageCount/>
    assert row.download_url == DOWNLOAD_URL
    with pytest.raises(UsitcEdisSourceError, match="names a document other than"):
        parse_attachments(ATTACHMENT_111112, document_id=999999)


def test_parse_attachment_retains_metadata_without_an_offered_download():
    (row,) = parse_attachments(ATTACHMENT_EMPTY_DOWNLOAD, document_id=880936)
    assert (row.id, row.document_id) == (2540777, 880936)
    assert row.file_size == 945347 and row.page_count == 53
    assert row.download_url is None
    with pytest.raises(UsitcEdisSourceError, match="names a document other than"):
        parse_attachments(ATTACHMENT_EMPTY_DOWNLOAD, document_id=1)


@pytest.mark.parametrize("filename", [None, "", r"\\mopey\prodimages\a7f\61BAF6"])
def test_attachment_retains_optional_original_filename_as_metadata(filename):
    # Guide pp. 10-11 includes an internal source path. Keep it as metadata;
    # current live responses and the retained fixtures omit this element.
    element = b"" if filename is None else f"<originalFileName>{filename}</originalFileName>".encode()
    body = ATTACHMENT_111112.replace(b"</attachment>", element + b"</attachment>")
    (row,) = parse_attachments(body, document_id=111112)
    assert row.original_file_name == (filename or None)
    assert attachment_record_dict(row)["originalFileName"] == (filename or None)
    assert row.download_url == DOWNLOAD_URL


def test_document_lookup_captures_one_known_document_without_a_page_walk():
    url = document_url(894762)
    transport = Transport({url: xml_response(DOCUMENT_894762)})
    with EdisAcquirer(budget=BUDGET, transport=transport) as acquirer:
        record, capture = acquirer.document(894762)
        assert acquirer.request_count == 1
    assert record.id == 894762 and record.security_level == "Public"
    assert record.attachment_list_url == attachment_url(894762)
    assert capture.body == DOCUMENT_894762
    assert [str(call.url) for call in transport.calls] == [url]


@pytest.mark.parametrize("status", [200, 404, 410])
def test_document_lookup_distinguishes_requested_empty_from_unavailable(status):
    transport = Transport({document_url(894762): xml_response(EMPTY_DOCUMENTS, status=status)})
    with EdisAcquirer(budget=BUDGET, transport=transport) as acquirer:
        if status == 200:
            record, capture = acquirer.document(894762)
            assert record is None and capture.body == EMPTY_DOCUMENTS
        else:
            with pytest.raises(UsitcEdisUnavailableError) as refused:
                acquirer.document(894762)
            assert attached_capture(refused.value).status_code == status
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "body,message",
    [
        (DOCUMENTS_337_3673, "more than one document"),
        (DOCUMENT_894762.replace(b"<id>894762</id>", b"<id>894763</id>"), "other than the one requested"),
    ],
)
def test_document_lookup_refuses_wrong_identity_or_multiple_rows_with_evidence(body, message):
    transport = Transport({document_url(894762): xml_response(body)})
    with (
        EdisAcquirer(budget=BUDGET, transport=transport) as acquirer,
        pytest.raises(UsitcEdisSourceError, match=message) as refused,
    ):
        acquirer.document(894762)
    assert attached_capture(refused.value).body == body
    assert refused.value.usitc_edis_acquisition["documentId"] == 894762


@pytest.mark.parametrize(
    "replacement,message",
    [
        (b"", "omitted its downloadUri"),
        (b"<downloadUri>https://example.com/file.pdf</downloadUri>", "EDIS locator"),
        (b"<downloadUri/>" * 2, "repeats downloadUri"),
        (b"<downloadUri>" + b"a" * 4097 + b"</downloadUri>", "length bound"),
    ],
)
def test_empty_download_support_preserves_attachment_shape_and_locator_checks(replacement, message):
    body = ATTACHMENT_EMPTY_DOWNLOAD.replace(b"<downloadUri/>", replacement)
    with pytest.raises(UsitcEdisSourceError, match=message):
        parse_attachments(body, document_id=880936)


def test_walk_advances_page_number_and_stops_at_the_empty_terminal_page():
    routes = {
        "https://edis.usitc.gov/data/investigation?investigationStatus=Active&pageNumber=1": xml_response(
            INVESTIGATIONS_ACTIVE
        ),
        "https://edis.usitc.gov/data/investigation?investigationStatus=Active&pageNumber=2": xml_response(
            EMPTY_INVESTIGATIONS
        ),
    }
    transport = Transport(routes)
    with EdisAcquirer(budget=BUDGET, transport=transport) as acquirer:
        pages = list(acquirer.investigations(investigation_url(status="Active")))
    assert [page.page_number for page in pages] == [1, 2]
    assert len(pages[0].records) == 6 and pages[1].is_empty
    assert [str(call.url) for call in transport.calls] == list(routes)
    assert pages[0].sha256 == "sha256:" + hashlib.sha256(INVESTIGATIONS_ACTIVE).hexdigest()


def test_walk_parses_pages_under_the_budget_page_bound_not_the_parser_default():
    # Whitespace between rows keeps the page byte-exact XML past the parser's 4 MiB default.
    padded = INVESTIGATION_731.replace(b"<investigations>", b"<investigations>" + b" " * (5 * 1024 * 1024))
    routes = {
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=1": xml_response(padded),
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=2": xml_response(EMPTY_INVESTIGATIONS),
    }
    budget = EdisBudget(4, 6 * 1024 * 1024, BUDGET.max_download_bytes, 7.0, 0.0)
    with EdisAcquirer(budget=budget, transport=Transport(routes)) as acquirer:
        pages = list(acquirer.investigations(investigation_url(number="731-1103")))
    assert len(pages[0].records) == 4 and pages[1].is_empty


def test_walk_refusals():
    """No page parameter, a repeated identity, an oversized page, a page bound and a 404 all refuse by name."""
    with EdisAcquirer(budget=BUDGET, transport=Transport({})) as acquirer:
        with pytest.raises(UsitcEdisSourceError, match="exactly one pageNumber"):
            list(acquirer.investigations("https://edis.usitc.gov/data/investigation"))
        with pytest.raises(UsitcEdisSourceError, match="exactly one pageNumber"):
            list(acquirer.investigations("https://edis.usitc.gov/data/investigation?pageNumber=1&pagenumber=2"))
    repeated = {
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=1": xml_response(INVESTIGATION_731),
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=2": xml_response(INVESTIGATION_731),
    }
    with (
        EdisAcquirer(budget=BUDGET, transport=Transport(repeated)) as acquirer,
        pytest.raises(UsitcEdisSourceError, match="same identity twice"),
    ):
        list(acquirer.investigations(investigation_url(number="731-1103")))
    oversized = (
        b"<results><investigations>"
        + b"".join(
            f"<investigation><investigationNumber>{i:06d}</investigationNumber><investigationPhase>Final"
            f"</investigationPhase><investigationStatus>Active</investigationStatus><investigationTitle>t"
            f"</investigationTitle><investigationType>t</investigationType><docketNumber/>"
            f"<documentListUri>https://edis.usitc.gov/data/document?investigationNumber={i:06d}"
            f"&amp;investigationPhase=Final</documentListUri></investigation>".encode()
            for i in range(PAGE_SIZE + 1)
        )
        + b"</investigations></results>"
    )
    routes = {"https://edis.usitc.gov/data/investigation?pageNumber=1": xml_response(oversized)}
    with (
        EdisAcquirer(budget=BUDGET, transport=Transport(routes)) as acquirer,
        pytest.raises(UsitcEdisSourceError, match=f"more than {PAGE_SIZE} rows"),
    ):
        list(acquirer.investigations(investigation_url()))
    bound_routes = {
        "https://edis.usitc.gov/data/investigation?pageNumber=1": xml_response(INVESTIGATIONS_ACTIVE),
        "https://edis.usitc.gov/data/investigation?pageNumber=2": xml_response(INVESTIGATION_731),
    }
    with (
        EdisAcquirer(budget=BUDGET, transport=Transport(bound_routes)) as acquirer,
        pytest.raises(UsitcEdisSourceError, match="page bound"),
    ):
        list(acquirer.investigations(investigation_url(), max_pages=2))
    missing = {"https://edis.usitc.gov/data/investigation?pageNumber=1": xml_response(b"<results/>", status=404)}
    with (
        EdisAcquirer(budget=BUDGET, transport=Transport(missing)) as acquirer,
        pytest.raises(UsitcEdisUnavailableError) as unavailable,
    ):
        list(acquirer.investigations(investigation_url()))
    assert attached_capture(unavailable.value).status_code == 404


def test_download_locator_grammar_and_pdf_proof():
    locator = attachment_download_locator(DOWNLOAD_URL)
    assert (locator.document_id, locator.attachment_id) == (111112, 111112)
    for bad in ("https://edis.usitc.gov/data/download/111112/111112?x=1", "https://edis.usitc.gov/data/download/a/b"):
        with pytest.raises(UsitcEdisSourceError):
            attachment_download_locator(bad)
    download = read_attachment_pdf(MINIMAL_PDF, url=DOWNLOAD_URL, final_url=DOWNLOAD_URL)
    assert (download.pdf_version, download.byte_size) == ("1.4", len(MINIMAL_PDF))
    with pytest.raises(UsitcEdisSourceError, match="final URL"):
        read_attachment_pdf(MINIMAL_PDF, url=DOWNLOAD_URL, final_url="https://edis.usitc.gov/login")
    with pytest.raises(UsitcEdisSourceError, match="magic"):
        read_attachment_pdf(b"<html>login</html>", url=DOWNLOAD_URL, final_url=DOWNLOAD_URL)
    with pytest.raises(UsitcEdisSourceError, match="trailer"):
        read_attachment_pdf(b"%PDF-1.4\ncut off", url=DOWNLOAD_URL, final_url=DOWNLOAD_URL)


def walled_result(
    *,
    body: bytes = MINIMAL_PDF,
    status: int = 200,
    content_type: str = "application/pdf",
    final_url: str = DOWNLOAD_URL,
) -> WalledFetchResult:
    """One scripted clean ladder answer, as the acquirer would receive it."""
    return WalledFetchResult(
        body=body,
        status_code=status,
        content_type=content_type,
        final_url=final_url,
        transport=LadderTransport.FIRECRAWL_RAW,
        wall=None,
        request_id="req-1",
    )


def pdf_handler(status: int = 200, body: bytes = MINIMAL_PDF, content_type: str = "application/pdf"):
    """A fresh publisher answer per request, so one route can be asked more than once."""
    return lambda _request: httpx.Response(
        status, headers={"Content-Type": content_type}, stream=httpx.ByteStream(body)
    )


def test_acquire_attachment_pdf_takes_the_ladder_answer_and_proves_it():
    requests: list[httpx.Request] = []
    publisher = pdf_handler()
    transport = httpx.MockTransport(lambda request: requests.append(request) or publisher(request))
    with EdisAcquirer(budget=BUDGET, transport=transport, clock=lambda: FIXED_INSTANT) as acquirer:
        download, capture = acquirer.acquire_attachment_pdf(DOWNLOAD_URL, declared_size=len(MINIMAL_PDF))
        assert acquirer.request_count == 1  # the DIRECT rung answered on this acquirer's own client
        # A call may narrow the byte bound, never raise it: the narrowed DIRECT rung refuses and escalates.
        with pytest.raises(WalledFetchError) as narrowed:
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, max_bytes=len(MINIMAL_PDF) - 1)
    assert (download.document_id, download.attachment_id, download.pdf_version) == (111112, 111112, "1.4")
    assert download.byte_size == len(MINIMAL_PDF)
    assert capture.body == MINIMAL_PDF and capture.status_code == 200
    assert capture.resolved_url == DOWNLOAD_URL and capture.content_type == "application/pdf"
    assert capture.observed_at == "2026-09-25T00:00:00Z"  # the acquirer's clock, not the wall clock
    assert narrowed.value.rung_outcomes[0].kind == "transport-error"
    assert [str(request.url) for request in requests] == [DOWNLOAD_URL, DOWNLOAD_URL]
    assert requests[0].headers["user-agent"] == "spicy-docs-usitc-edis/1.0"
    assert "authorization" not in requests[0].headers


def test_acquire_attachment_pdf_reads_a_clean_404_as_absence_not_a_pdf():
    transport = httpx.MockTransport(pdf_handler(404, b"<results/>", "text/xml"))
    with (
        EdisAcquirer(budget=BUDGET, transport=transport) as acquirer,
        pytest.raises(UsitcEdisUnavailableError) as unavailable,
    ):
        acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
    assert attached_capture(unavailable.value).status_code == 404


def test_ladder_resolves_providers_once_and_skips_a_keyless_rung_uncharged_and_unpaced(monkeypatch):
    from spicy_docs.transport import capture as capture_module

    elapsed, resolved = [0.0], []
    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", lambda delay: elapsed.__setitem__(0, elapsed[0] + delay))
    monkeypatch.setattr(
        ladder.ProxyFetchers,
        "from_environment",
        classmethod(lambda cls: resolved.append(None) or cls("no Zyte credential", "no Firecrawl credential")),
    )
    directs: list[float] = []

    def walled(_request):
        directs.append(elapsed[0])
        return httpx.Response(403, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(b"Access Denied"))

    budget = EdisBudget(3, BUDGET.max_page_bytes, BUDGET.max_download_bytes, 9.0, 2.0)
    with EdisAcquirer(budget=budget, transport=httpx.MockTransport(walled)) as acquirer:
        for _ in range(2):
            with pytest.raises(WalledFetchError) as raised:
                acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
            assert [outcome.kind for outcome in raised.value.rung_outcomes] == [
                "wall",
                "credential-error",
                "credential-error",
            ]
            assert acquirer.request_count == 1
            context = raised.value.usitc_edis_acquisition
            assert context["route"] == "walled-ladder" and context["requestCount"] == 1
    # Keys are resolved once per acquirer; the keyless rungs neither count nor wait,
    # so the second DIRECT attempt is paced from the first alone.
    assert resolved == [None]
    assert directs == [0.0, 2.0]


def test_acquire_attachment_pdf_still_proves_media_type_magic_final_url_and_declared_size(monkeypatch):
    def answered(result):
        monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: result)

    with EdisAcquirer(budget=BUDGET) as acquirer:
        answered(walled_result(body=b"<html>login</html>", content_type="text/html"))
        with pytest.raises(UsitcEdisSourceError, match="Content-Type"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
        answered(walled_result(body=b"<html>login</html>"))
        with pytest.raises(UsitcEdisSourceError, match="magic"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
        answered(walled_result(final_url="https://edis.usitc.gov/login"))
        with pytest.raises(UsitcEdisSourceError, match="final URL"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
        answered(walled_result())
        with pytest.raises(UsitcEdisSourceError, match="differs from the size"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, declared_size=len(MINIMAL_PDF) + 1)


def test_acquire_attachment_pdf_refuses_bad_arguments_before_any_rung(monkeypatch):
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("no rung must run"))
    monkeypatch.setattr(edis_api, "credentialed_download", lambda *_a, **_k: pytest.fail("no rung must run"))
    with EdisAcquirer(budget=BUDGET) as acquirer:
        with pytest.raises(UsitcEdisSourceError, match="larger than"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, declared_size=BUDGET.max_download_bytes + 1)
        for bad in (-1, True, 1.5, "10"):
            with pytest.raises(UsitcEdisSourceError, match="non-negative integer"):
                acquirer.acquire_attachment_pdf(DOWNLOAD_URL, declared_size=bad)
        # A named transport without a token must not silently take the anonymous ladder.
        for route in ("direct", "zyte"):
            with pytest.raises(UsitcEdisSourceError, match="needs a download token"):
                acquirer.acquire_attachment_pdf(DOWNLOAD_URL, credentialed_transport=route)
        with pytest.raises(UsitcEdisSourceError, match="must be direct or zyte"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token="edis-test-token", credentialed_transport="other")


def test_feed_parses_notification_items_and_their_confidential_flags():
    feed = parse_edis_feed(FEED_2022)
    assert feed.title == "USITC Document Notification Syndication Feed"
    assert [item.document_id for item in feed.items] == [770876, 770964, 770981, 770984]
    assert [item.confidential for item in feed.items] == [True, False, False, True]
    assert [item.document_type for item in feed.items] == [
        "Motion Response/Reply",
        "Pre-Hearing Statement",
        "Pre-Hearing Statement",
        "Brief Filed With ALJ",
    ]
    assert feed.items[0].public_document_url == "https://edis.usitc.gov/external/search/document/770876"
    assert feed.items[0].public_document_id == 770876


def test_feed_refusals():
    with pytest.raises(UsitcEdisSourceError, match="numeric document guid"):
        parse_edis_feed(FEED_2022.replace(b"<guid>770876</guid>", b"<guid>not-a-number</guid>"))
    with pytest.raises(UsitcEdisSourceError, match="other than its guid"):
        parse_edis_feed(FEED_2022.replace(b"/external/search/document/770876", b"/external/search/document/770964"))


def pilot_routes(attachment_responses: dict[int, httpx.Response]) -> dict[str, httpx.Response]:
    routes = {
        "https://edis.usitc.gov/data/investigation/337-3673?pageNumber=1": xml_response(INVESTIGATION_337_3673),
        "https://edis.usitc.gov/data/investigation/337-3673?pageNumber=2": xml_response(EMPTY_INVESTIGATIONS),
        "https://edis.usitc.gov/data/document?investigationNumber=337-3673&investigationPhase=Violation&pageNumber=1": (
            xml_response(DOCUMENTS_337_3673)
        ),
        "https://edis.usitc.gov/data/document?investigationNumber=337-3673&investigationPhase=Violation&pageNumber=2": (
            xml_response(EMPTY_DOCUMENTS)
        ),
    }
    for document_id, response in attachment_responses.items():
        routes[f"https://edis.usitc.gov/data/attachment/{document_id}"] = response
    return routes


def pilot_call_order(attachment_ids: list[int]) -> list[str]:
    # The investigation walk stops at the page that states the phase: the
    # terminal empty page of that listing is never requested.
    return [
        "https://edis.usitc.gov/data/investigation/337-3673?pageNumber=1",
        "https://edis.usitc.gov/data/document?investigationNumber=337-3673&investigationPhase=Violation&pageNumber=1",
        "https://edis.usitc.gov/data/document?investigationNumber=337-3673&investigationPhase=Violation&pageNumber=2",
        *[f"https://edis.usitc.gov/data/attachment/{document_id}" for document_id in attachment_ids],
    ]


def test_reader_completes_one_pilot_investigation_with_keys_and_failures():
    transport = Transport(
        pilot_routes(
            {
                793615: xml_response(attachment_page(793615)),
                793596: xml_response(b"<results/>", status=404),
                793595: xml_response(attachment_page(793595)),
            }
        )
    )
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="337-3673",
        investigation_phase="Violation",
        transport=transport,
    )
    records = list(reader.iter_records())
    assert [row["documentId"] for row in records] == [793615, 793595]
    first = records[0]
    assert first["documentType"] == "Complaint" and first["firmOrganization"] == "Latham & Watkins LLP"
    assert first["documentDate"] == "2023/04/03 00:00:00"
    assert first["documentListPageSha256"] == "sha256:" + hashlib.sha256(DOCUMENTS_337_3673).hexdigest()
    assert [attachment["documentId"] for attachment in first["attachments"]] == [793615]
    assert first["attachmentListSha256"] == "sha256:" + hashlib.sha256(attachment_page(793615)).hexdigest()
    assert reader.last_keys == ["793615", "793595"]
    assert reader.failed_keys == ["793596"]
    assert [str(call.url) for call in transport.calls] == pilot_call_order([793615, 793596, 793595])


def test_reader_retries_a_previous_run_failed_key_first():
    transport = Transport(
        pilot_routes(
            {
                793615: xml_response(attachment_page(793615)),
                793596: xml_response(attachment_page(793596)),
                793595: xml_response(attachment_page(793595)),
            }
        )
    )
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="337-3673",
        investigation_phase="Violation",
        retry_keys=["793596", "999999"],
        transport=transport,
    )
    records = list(reader.iter_records())
    assert [row["documentId"] for row in records] == [793596, 793615, 793595]
    assert reader.last_keys == ["793596", "793615", "793595"] and reader.failed_keys == []
    # A key the listing no longer states is surfaced, never silently dropped.
    assert reader.unlisted_retry_keys == ["999999"]
    assert [str(call.url) for call in transport.calls] == pilot_call_order([793596, 793615, 793595])


def test_reader_completes_metadata_when_an_attachment_has_no_download():
    attachment_bodies = {document_id: attachment_page(document_id) for document_id in (793615, 793596, 793595)}
    attachment_bodies[793596] = attachment_bodies[793596].replace(DOWNLOAD_URL.encode(), b"")
    transport = Transport(pilot_routes({key: xml_response(body) for key, body in attachment_bodies.items()}))
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="337-3673",
        investigation_phase="Violation",
        fail_fast=True,
        transport=transport,
    )
    records = list(reader.iter_records())
    confidential = next(row for row in records if row["documentId"] == 793596)
    assert confidential["securityLevel"] == "Confidential"
    assert confidential["attachments"][0]["downloadUri"] is None
    assert confidential["attachments"][0]["fileSize"] == 304508
    assert confidential["attachmentListSha256"] == "sha256:" + hashlib.sha256(attachment_bodies[793596]).hexdigest()
    assert reader.last_keys == ["793615", "793596", "793595"] and reader.failed_keys == []
    assert [str(call.url) for call in transport.calls] == pilot_call_order([793615, 793596, 793595])


def test_reader_fail_fast_turns_a_failed_attachment_page_into_a_raise():
    transport = Transport(
        pilot_routes(
            {
                793615: xml_response(attachment_page(793615)),
                793596: xml_response(b"<results/>", status=404),
                793595: xml_response(attachment_page(793595)),
            }
        )
    )
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="337-3673",
        investigation_phase="Violation",
        fail_fast=True,
        transport=transport,
    )
    with pytest.raises(UsitcEdisUnavailableError):
        list(reader.iter_records())
    assert reader.last_keys == ["793615"]
    assert reader.failed_keys == ["793596"]


def test_reader_refuses_a_phase_the_listing_does_not_state():
    routes = {
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=1": xml_response(INVESTIGATION_731),
        "https://edis.usitc.gov/data/investigation/731-1103?pageNumber=2": xml_response(EMPTY_INVESTIGATIONS),
    }
    transport = Transport(routes)
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="731-1103",
        investigation_phase="Nowhere",
        transport=transport,
    )
    with pytest.raises(UsitcEdisSourceError, match="states no phase"):
        list(reader.iter_records())
    assert reader.last_keys == [] and reader.failed_keys == []
    assert [str(call.url) for call in transport.calls] == list(routes)


@pytest.mark.parametrize(
    "route_kind,old,new",
    [
        ("investigation", b"337-3673", b"337-1145"),
        ("document", b"337-3673", b"337-1145"),
        # A shorter number is not what a partial-number match adds; it still refuses.
        ("document", b"337-3673", b"337-367"),
        (
            "document",
            b"<investigationPhase>Violation</investigationPhase>",
            b"<investigationPhase>Review</investigationPhase>",
        ),
    ],
)
def test_reader_refuses_rows_outside_the_requested_investigation(route_kind, old, new):
    routes = pilot_routes({})
    url = next(url for url in routes if f"/data/{route_kind}" in url and "pageNumber=1" in url)
    original = INVESTIGATION_337_3673 if route_kind == "investigation" else DOCUMENTS_337_3673
    wrong_scope = original.replace(old, new)
    assert wrong_scope != original
    routes[url] = xml_response(wrong_scope)
    transport = Transport(routes)
    reader = UsitcEdisReader(
        budget=BUDGET, investigation_number="337-3673", investigation_phase="Violation", transport=transport
    )
    with pytest.raises(UsitcEdisSourceError, match="outside the requested investigation") as raised:
        list(reader.iter_records())
    assert attached_capture(raised.value).body == wrong_scope
    assert raised.value.refused_response.response_bytes == wrong_scope
    assert reader.last_keys == [] and reader.failed_keys == []
    assert all("/attachment/" not in str(request.url) for request in transport.calls)


def test_reader_treats_an_empty_listing_as_requested_empty_not_absence():
    routes = {
        "https://edis.usitc.gov/data/investigation/337-3673?pageNumber=1": xml_response(EMPTY_INVESTIGATIONS),
    }
    transport = Transport(routes)
    reader = UsitcEdisReader(
        budget=BUDGET,
        investigation_number="337-3673",
        investigation_phase="Violation",
        transport=transport,
    )
    with pytest.raises(UsitcEdisSourceError, match="states no phase"):
        list(reader.iter_records())
    assert [str(call.url) for call in transport.calls] == list(routes)


def test_budget_refuses_unbounded_values():
    for kwargs in (
        {"max_requests": 0},
        {"max_page_bytes": 0},
        {"max_download_bytes": 0},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ):
        valid = {
            "max_requests": 4,
            "max_page_bytes": 1024,
            "max_download_bytes": 1024,
            "timeout_seconds": 7.0,
            "min_request_interval_seconds": 0.0,
        }
        valid.update(kwargs)
        with pytest.raises(ValueError):
            EdisBudget(**valid)


def credentialed_capture(
    *,
    body: bytes = MINIMAL_PDF,
    status: int = 200,
    content_type: str = "application/pdf",
    final_url: str = DOWNLOAD_URL,
) -> CapturedBodyResponse:
    """One scripted credentialed answer, as ``credentialed_download`` would return it."""
    return CapturedBodyResponse(
        requested_url=DOWNLOAD_URL,
        resolved_url=final_url,
        status_code=status,
        content_type=content_type,
        observed_at="2026-09-24T00:00:00Z",
        body=body,
    )


def test_acquire_attachment_pdf_takes_the_credentialed_route_and_proves_it(monkeypatch):
    calls: dict[str, object] = {}

    def fake_credentialed(url, *, token, max_bytes, timeout_seconds, route, before_request, clock):
        before_request()
        calls.update(
            url=url, token=token, max_bytes=max_bytes, timeout_seconds=timeout_seconds, route=route, clock=clock()
        )
        return credentialed_capture()

    monkeypatch.setattr(edis_api, "credentialed_download", fake_credentialed)
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("the ladder must not run"))
    token = "edis-test-token"
    with EdisAcquirer(budget=BUDGET, clock=lambda: FIXED_INSTANT) as acquirer:
        download, capture = acquirer.acquire_attachment_pdf(DOWNLOAD_URL, declared_size=len(MINIMAL_PDF), token=token)
    assert calls["url"] == DOWNLOAD_URL
    assert calls["token"] == token
    assert calls["max_bytes"] == BUDGET.max_download_bytes
    assert calls["timeout_seconds"] == BUDGET.timeout_seconds
    assert calls["route"] == "direct" and calls["clock"] == FIXED_INSTANT
    assert (download.document_id, download.attachment_id, download.pdf_version) == (111112, 111112, "1.4")
    assert capture.body == MINIMAL_PDF and capture.status_code == 200
    assert capture.resolved_url == DOWNLOAD_URL and capture.content_type == "application/pdf"
    with EdisAcquirer(budget=BUDGET) as acquirer:
        acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token, credentialed_transport="zyte")
    assert calls["route"] == "zyte"


def test_acquire_attachment_pdf_still_proves_credentialed_bytes(monkeypatch):
    results: dict[str, object] = {}

    def fake_credentialed(url, *, token, max_bytes, timeout_seconds, route, before_request, clock):
        before_request()
        return credentialed_capture(
            body=results["body"],
            status=results.get("status", 200),
            content_type=results.get("content_type", "application/pdf"),
            final_url=results.get("final_url", DOWNLOAD_URL),
        )

    monkeypatch.setattr(edis_api, "credentialed_download", fake_credentialed)
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("the ladder must not run"))
    token = "edis-test-token"
    with EdisAcquirer(budget=BUDGET) as acquirer:
        results.update(body=b"<html>login</html>", content_type="text/html")
        with pytest.raises(UsitcEdisSourceError, match="Content-Type"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
        results.update(body=b"<html>login</html>", content_type="application/pdf")
        with pytest.raises(UsitcEdisSourceError, match="magic"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
        results.update(final_url="https://edis.usitc.gov/login")
        with pytest.raises(UsitcEdisSourceError, match="final URL"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
        results.update(body=MINIMAL_PDF, final_url=DOWNLOAD_URL)
        with pytest.raises(UsitcEdisSourceError, match="differs from the size"):
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token, declared_size=len(MINIMAL_PDF) + 1)
        results.update(status=404, content_type="text/xml", body=b"<results/>")
        with pytest.raises(UsitcEdisUnavailableError) as unavailable:
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
    assert attached_capture(unavailable.value).status_code == 404


def test_credentialed_refusal_and_wall_pass_through_with_context_and_no_token(monkeypatch):
    token = "edis-test-token"

    def refuse_401(*_args, **_kwargs):
        error = CredentialRefusedError(
            "USITC EDIS answered 401 for the credentialed attachment download: access was refused. "
            "Stopping rather than continuing or falling back."
        )
        error.__dict__["capture"] = credentialed_capture(status=401, content_type=None, body=b"denied")
        raise error

    monkeypatch.setattr(edis_api, "credentialed_download", refuse_401)
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("the ladder must not run"))
    with EdisAcquirer(budget=BUDGET) as acquirer:
        key = acquirer.context_key
        with pytest.raises(CredentialRefusedError) as raised:
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
    context = raised.value.__dict__.get(key, {})
    assert context["route"] == "credentialed-direct" and context["url"] == DOWNLOAD_URL
    assert attached_capture(raised.value).status_code == 401
    assert token not in json.dumps(context) and token not in str(raised.value)

    def wall_answer(*_args, **_kwargs):
        error = UsitcEdisSourceError("USITC EDIS credentialed download answered a wall page ('Access Denied')")
        error.__dict__["capture"] = credentialed_capture(status=403, content_type="text/html", body=b"Access Denied")
        raise error

    monkeypatch.setattr(edis_api, "credentialed_download", wall_answer)
    with (
        EdisAcquirer(budget=BUDGET) as acquirer,
        pytest.raises(UsitcEdisSourceError, match="wall page") as raised_wall,
    ):
        acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=token)
    context = raised_wall.value.__dict__.get(key, {})
    assert context["route"] == "credentialed-direct"
    assert token not in json.dumps(context) and token not in str(raised_wall.value)


def test_acquire_attachment_pdf_refuses_a_bad_token_before_any_rung(monkeypatch):
    monkeypatch.setattr(
        edis_api, "credentialed_download", lambda *_a, **_k: pytest.fail("no credentialed rung must run")
    )
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("no ladder rung must run"))
    with EdisAcquirer(budget=BUDGET) as acquirer:
        for bad in ("", " 123 ", "123 ", "x" * 5000):
            with pytest.raises(UsitcEdisSourceError):
                acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token=bad)


class _ProviderResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def _provider_response(body: bytes, *, status: int = 200, content_type: str | None = "application/pdf") -> bytes:
    headers = [] if content_type is None else [{"name": "Content-Type", "value": content_type}]
    return json.dumps(
        {
            "httpResponseBody": base64.b64encode(body).decode(),
            "httpResponseHeaders": headers,
            "statusCode": status,
            "url": DOWNLOAD_URL,
        }
    ).encode()


def test_credentialed_download_sends_the_bearer_header_only_to_an_edis_download_locator(monkeypatch):
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: pytest.fail("no provider credential must be read for a refused locator")),
    )
    for bad in ("https://evil.example/data/download/111112/111112", "https://edis.usitc.gov/data/attachment/1"):
        with pytest.raises(UsitcEdisSourceError):
            edis_credentialed.credentialed_download(bad, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0)


def test_credentialed_download_sends_the_bearer_header_and_returns_the_capture(monkeypatch):
    requests: list[object] = []

    def open_request(request, *, timeout: float):
        requests.append((request, timeout))
        return _ProviderResponse(_provider_response(MINIMAL_PDF))

    monkeypatch.setattr(zyte_source.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: ZyteHttpFetcher(token="zyte-test-token")),
    )
    capture = edis_credentialed.credentialed_download(
        DOWNLOAD_URL, token="edis-test-token", max_bytes=1024 * 1024, timeout_seconds=9.0, route="zyte"
    )
    assert capture.body == MINIMAL_PDF and capture.status_code == 200
    assert capture.content_type == "application/pdf" and capture.resolved_url == DOWNLOAD_URL
    sent = json.loads(requests[0][0].data)
    assert sent["customHttpRequestHeaders"] == [{"name": "Authorization", "value": "Bearer edis-test-token"}]
    assert sent["httpResponseBody"] is True and sent["url"] == DOWNLOAD_URL
    assert requests[0][1] == 9.0
    assert b"zyte-test-token" not in requests[0][0].data


def test_credentialed_download_refuses_a_wall_a_refusal_and_a_reflected_credential(monkeypatch):
    token = "edis-test-token"
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: ZyteHttpFetcher(token="zyte-test-token")),
    )

    def answer(body: bytes, *, status: int = 200, content_type: str | None = "application/pdf") -> None:
        monkeypatch.setattr(
            zyte_source.urllib.request,
            "urlopen",
            lambda *_a, **_k: _ProviderResponse(_provider_response(body, status=status, content_type=content_type)),
        )

    answer(b"You don't have permission to access", status=403, content_type="text/html")
    with pytest.raises(CredentialRefusedError) as walled:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    assert attached_capture(walled.value) is None
    assert walled.value.refused_response.response_bytes is None
    answer(b"<html>denied</html>", status=401, content_type="text/html")
    with pytest.raises(CredentialRefusedError) as refused:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    assert attached_capture(refused.value) is None
    assert refused.value.refused_response.response_bytes is None
    assert token not in str(refused.value) and token not in str(walled.value)
    answer(b"<html>" + token.encode() + b"</html>")
    with pytest.raises(UsitcEdisSourceError, match="reflected") as reflected:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    assert attached_capture(reflected.value) is None
    assert reflected.value.refused_response.response_bytes is None


def test_credentialed_download_bounds_the_answer_and_names_only_provider_slugs(monkeypatch):
    token = "edis-test-token"
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: ZyteHttpFetcher(token="zyte-test-token")),
    )
    monkeypatch.setattr(
        zyte_source.urllib.request,
        "urlopen",
        lambda *_a, **_k: _ProviderResponse(_provider_response(b"%PDF-1.4\n" + b"x" * 64)),
    )
    with pytest.raises(UsitcEdisSourceError, match="exceeds max_bytes") as oversized:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=token, max_bytes=32, timeout_seconds=9.0, route="zyte"
        )
    assert oversized.value.refused_response.unavailable_reason == "response-byte-limit"
    assert oversized.value.refused_response.response_bytes is None

    def provider_failed(request, *, timeout: float):
        raise urllib.error.HTTPError(
            request.full_url, 500, "provider", {}, io.BytesIO(b'{"type":"/download/temporary-error"}')
        )

    monkeypatch.setattr(zyte_source.urllib.request, "urlopen", provider_failed)
    with pytest.raises(UsitcEdisSourceError, match="temporary-error") as provider_error:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    assert token not in str(provider_error.value)


def test_credentialed_token_validation_never_repeats_the_secret():
    secret = " secret-value "
    # Seven characters: scrub_credential's literal pass would skip a token this short.
    for bad in (
        secret,
        "",
        "secret-value ",
        "'secret-value'",
        "secret\r\nvalue",
        "secret\x00value",
        "x" * 5000,
        "seven77",
    ):
        with pytest.raises(UsitcEdisSourceError) as raised:
            edis_credentialed.validate_edis_token(bad)
        assert "secret-value" not in str(raised.value)
    assert edis_credentialed.validate_edis_token("a" * 4096) == "a" * 4096
    assert edis_credentialed.validate_edis_token("eight888") == "eight888"


def direct_client(monkeypatch, handler):
    """Keep the actual HTTPX client behavior while supplying one scripted publisher."""
    client = httpx.Client
    settings = []

    def create_client(**kwargs):
        settings.append(kwargs)
        return client(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(httpx, "Client", create_client)
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: pytest.fail("direct capture must not read a proxy credential")),
    )
    return settings


def test_credentialed_direct_download_sends_one_bearer_get_without_a_proxy(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": str(len(MINIMAL_PDF))},
            stream=httpx.ByteStream(MINIMAL_PDF),
        )

    settings = direct_client(monkeypatch, handler)
    result = edis_credentialed.credentialed_download(
        DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0
    )
    assert result.body == MINIMAL_PDF and result.status_code == 200
    assert len(requests) == 1 and requests[0].method == "GET" and str(requests[0].url) == DOWNLOAD_URL
    assert requests[0].headers["Authorization"] == "Bearer edis-test-token"
    assert requests[0].headers["Accept-Encoding"] == "identity"
    assert settings[0]["timeout"].read == 9.0
    assert settings[0]["follow_redirects"] is False and settings[0]["trust_env"] is False


@pytest.mark.parametrize("status", [401, 403])
def test_credentialed_direct_refusal_stops_with_the_retained_live_response_shape(monkeypatch, status):
    requests = []

    def handler(request):
        requests.append(request)
        # Both live controls returned an empty body and no Content-Type.
        return httpx.Response(status, headers={"Content-Length": "0"}, stream=httpx.ByteStream(b""))

    direct_client(monkeypatch, handler)
    with pytest.raises(CredentialRefusedError) as raised:
        edis_credentialed.credentialed_download(
            "https://edis.usitc.gov/data/download/894762/2620262",
            token="edis-test-token",
            max_bytes=1024,
            timeout_seconds=9.0,
        )
    assert len(requests) == 1
    capture = attached_capture(raised.value)
    assert capture is None
    assert raised.value.refused_response.response_bytes is None
    assert str(status) in str(raised.value)
    assert "edis-test-token" not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "body", "headers", "message"),
    [
        (200, b"Access Denied", {}, "wall page"),
        (302, b"", {"Location": "https://another.example/file.pdf"}, "HTTP 302"),
        (500, MINIMAL_PDF, {"Content-Type": "application/pdf"}, "HTTP 500"),
    ],
)
def test_credentialed_direct_wall_redirect_and_error_do_not_fall_back(monkeypatch, status, body, headers, message):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))

    direct_client(monkeypatch, handler)
    with pytest.raises(UsitcEdisSourceError, match=message) as raised:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0
        )
    assert len(requests) == 1
    if status != 500:
        assert attached_capture(raised.value).body == body


@pytest.mark.parametrize("reflection", ["body", "content-type"])
def test_credentialed_direct_reflected_token_is_never_retained(monkeypatch, reflection):
    token = "edis-test-token"

    def handler(_request):
        body = token.encode() if reflection == "body" else b"refused"
        content_type = token if reflection == "content-type" else "text/plain"
        return httpx.Response(200, headers={"Content-Type": content_type}, stream=httpx.ByteStream(body))

    direct_client(monkeypatch, handler)
    with pytest.raises(UsitcEdisSourceError, match="reflected credential") as raised:
        edis_credentialed.credentialed_download(DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0)
    assert token not in str(raised.value)
    assert attached_capture(raised.value) is None
    assert raised.value.refused_response.response_bytes is None


@pytest.mark.parametrize(
    ("headers", "body", "message"),
    [
        ({"Content-Length": "9999"}, b"", "byte bound"),
        ({}, b"x" * 1025, "byte bound"),
        ({"Content-Length": "3"}, b"xx", "differs from Content-Length"),
        ({"Content-Length": "bad"}, b"xx", "Content-Length is invalid"),
        ({"Content-Encoding": "gzip"}, b"xx", "unsupported content encoding"),
    ],
)
def test_credentialed_direct_bounds_and_checks_the_whole_response(monkeypatch, headers, body, message):
    direct_client(monkeypatch, lambda _request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body)))
    with pytest.raises(UsitcEdisSourceError, match=message):
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0
        )


def test_credentialed_direct_transport_error_never_copies_transport_text(monkeypatch):
    """The shared client names a failure in its own fixed words; the transport's message never travels."""
    token = "edis-test-token"

    def handler(_request):
        raise httpx.ConnectError("transport message with " + token)

    direct_client(monkeypatch, handler)
    with pytest.raises(UsitcEdisSourceError, match="transport failed") as raised:
        edis_credentialed.credentialed_download(DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0)
    assert "transport message" not in str(raised.value)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert token not in "".join(traceback.format_exception(raised.value))


def test_credentialed_direct_reflection_inside_a_shared_client_error_is_never_retained(monkeypatch):
    """A size mismatch carries the complete body; a reflected token in it must not survive in any chain."""
    token = "edis-test-token"
    body = b"echo " + token.encode()
    headers = {"Content-Type": "text/plain", "Content-Length": str(len(body) + 5)}
    direct_client(monkeypatch, lambda _request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body)))
    with pytest.raises(UsitcEdisSourceError, match="reflected credential") as raised:
        edis_credentialed.credentialed_download(DOWNLOAD_URL, token=token, max_bytes=1024, timeout_seconds=9.0)
    assert attached_capture(raised.value) is None
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert token not in "".join(traceback.format_exception(raised.value))


def test_credentialed_transport_selection_refuses_unknown_values_before_a_request(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("invalid transport made a request"))
    with pytest.raises(UsitcEdisSourceError, match="transport must be direct or zyte"):
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0, route="other"
        )


@pytest.mark.parametrize("route", ["direct", "zyte", "anonymous"])
def test_downloads_share_metadata_pacing_and_report_each_operation_attempts(monkeypatch, route):
    from spicy_docs.transport import capture as capture_module

    elapsed = [0.0]
    attempts = []

    def sleep(delay):
        elapsed[0] += delay

    def publisher(request):
        if str(request.url) == DOWNLOAD_URL:  # the ladder's DIRECT rung runs on this acquirer's own client
            attempts.append(("direct", elapsed[0]))
            return httpx.Response(403, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(b"Access Denied"))
        attempts.append(("metadata", elapsed[0]))
        return httpx.Response(
            200, headers={"Content-Type": "application/xml"}, stream=httpx.ByteStream(ATTACHMENT_111112)
        )

    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", sleep)
    budget = EdisBudget(2, BUDGET.max_page_bytes, BUDGET.max_download_bytes, 9.0, 2.0)
    # Build the metadata client before substituting the independent direct-download client.
    acquirer = EdisAcquirer(budget=budget, transport=httpx.MockTransport(publisher))
    if route == "direct":

        def download(_request):
            attempts.append(("direct", elapsed[0]))
            return httpx.Response(
                200, headers={"Content-Type": "application/pdf"}, stream=httpx.ByteStream(MINIMAL_PDF)
            )

        direct_client(monkeypatch, download)
    else:

        def provider(_request, *, timeout):
            attempts.append(("zyte", elapsed[0]))
            return _ProviderResponse(_provider_response(MINIMAL_PDF))

        monkeypatch.setattr(zyte_source.urllib.request, "urlopen", provider)
        fetcher = ZyteHttpFetcher(token="zyte-test-token")
        if route == "zyte":
            monkeypatch.setattr(edis_credentialed.ZyteHttpFetcher, "from_environment", classmethod(lambda cls: fetcher))
        else:
            monkeypatch.setattr(
                ladder.ProxyFetchers,
                "from_environment",
                classmethod(lambda cls: cls(fetcher, "no Firecrawl credential in tests")),
            )
    with acquirer:
        acquirer.attachments(111112)
        assert acquirer.request_count == 1
        kwargs = {} if route == "anonymous" else {"token": "edis-test-token", "credentialed_transport": route}
        acquirer.acquire_attachment_pdf(DOWNLOAD_URL, **kwargs)
        assert acquirer.request_count == (2 if route == "anonymous" else 1)
        acquirer.attachments(111112)
        assert acquirer.request_count == 1
    expected_routes = (
        ["metadata", "direct", "zyte", "metadata"] if route == "anonymous" else ["metadata", route, "metadata"]
    )
    assert [name for name, _time in attempts] == expected_routes
    assert [moment for _name, moment in attempts] == [2.0 * index for index in range(len(attempts))]


def test_anonymous_pdf_request_cap_stops_after_one_wall_and_counts_the_attempt(monkeypatch):
    attempts = []

    def walled(_request):
        attempts.append("direct")
        return httpx.Response(403, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(b"Access Denied"))

    monkeypatch.setattr(
        ladder.ProxyFetchers,
        "from_environment",
        classmethod(lambda cls: cls(ZyteHttpFetcher(token="zyte-test-token"), "no Firecrawl credential in tests")),
    )
    monkeypatch.setattr(
        zyte_source.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("request cap did not stop Zyte")
    )
    budget = EdisBudget(1, BUDGET.max_page_bytes, BUDGET.max_download_bytes, 9.0, 0)
    with EdisAcquirer(budget=budget, transport=httpx.MockTransport(walled)) as acquirer:
        with pytest.raises(WalledFetchError) as raised:
            acquirer.acquire_attachment_pdf(DOWNLOAD_URL)
        assert acquirer.request_count == 1
        assert raised.value.usitc_edis_acquisition["requestCount"] == 1
    assert attempts == ["direct"]


@pytest.mark.parametrize("route", ["direct", "zyte"])
def test_credential_refusal_keeps_one_attempt_and_never_uses_another_route(monkeypatch, route):
    if route == "direct":
        acquirer = EdisAcquirer(budget=BUDGET)
        direct_client(monkeypatch, lambda _request: httpx.Response(403, stream=httpx.ByteStream(b"")))
    else:
        acquirer = EdisAcquirer(budget=BUDGET)
        monkeypatch.setattr(
            edis_credentialed.ZyteHttpFetcher,
            "from_environment",
            classmethod(lambda cls: ZyteHttpFetcher(token="zyte-test-token")),
        )
        monkeypatch.setattr(
            zyte_source.urllib.request,
            "urlopen",
            lambda *_a, **_k: _ProviderResponse(_provider_response(b"", status=403, content_type=None)),
        )
    monkeypatch.setattr(ladder, "walled_fetch", lambda *_a, **_k: pytest.fail("credential refusal fell back"))
    with acquirer, pytest.raises(CredentialRefusedError) as raised:
        acquirer.acquire_attachment_pdf(DOWNLOAD_URL, token="edis-test-token", credentialed_transport=route)
    assert acquirer.request_count == 1
    assert raised.value.usitc_edis_acquisition["requestCount"] == 1


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"Access Denied", {}),
        (b"edis-test-token", {}),
        (b"", {"Content-Encoding": "gzip"}),
        (b"", {"Content-Length": "999999999"}),
        (b"", {"Content-Length": "invalid"}),
    ],
)
def test_direct_auth_status_stops_before_body_or_header_validation(monkeypatch, status, body, headers):
    direct_client(monkeypatch, lambda _request: httpx.Response(status, headers=headers, stream=httpx.ByteStream(body)))
    with pytest.raises(CredentialRefusedError) as raised:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0
        )
    assert attached_capture(raised.value) is None
    assert raised.value.refused_response.response_bytes is None
    assert "edis-test-token" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("status", [401, 403])
def test_zyte_auth_status_stops_even_when_the_body_metadata_is_unusable(monkeypatch, status):
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: ZyteHttpFetcher(token="zyte-test-token")),
    )
    payload = json.dumps(
        {"statusCode": status, "url": "edis-test-token", "httpResponseBody": "invalid-base64"}
    ).encode()
    monkeypatch.setattr(zyte_source.urllib.request, "urlopen", lambda *_a, **_k: _ProviderResponse(payload))
    with pytest.raises(CredentialRefusedError) as raised:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token="edis-test-token", max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    assert attached_capture(raised.value) is None
    assert raised.value.refused_response.response_bytes is None
    assert "edis-test-token" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize(
    "failure", ["open-oserror", "read-oserror", "http-target-slug", "http-proxy-slug", "json-field"]
)
def test_zyte_failures_scrub_both_credentials_from_messages_and_tracebacks_and_close_errors(monkeypatch, failure):
    target, proxy = "targetsecret", "proxysecret"
    provider_errors = []
    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: ZyteHttpFetcher(token=proxy)),
    )

    class ReadFailure(_ProviderResponse):
        def read(self, _limit):
            raise OSError(f"{target} and {proxy}")

    def open_request(request, **_kwargs):
        if failure == "open-oserror":
            raise OSError(f"{target} and {proxy}")
        if failure == "read-oserror":
            return ReadFailure(b"")
        if failure.startswith("http-"):
            slug = target if failure == "http-target-slug" else proxy
            error = urllib.error.HTTPError(
                request.full_url,
                520,
                f"{target} and {proxy}",
                {},
                io.BytesIO(json.dumps({"type": f"/{slug}"}).encode()),
            )
            provider_errors.append(error)
            raise error
        # Envelope keys are the provider's own (target bytes arrive Base64 in a value), so the
        # shared parser may name a repeated key; the credentials must still never appear.
        return _ProviderResponse(b'{"statusCode":200,"statusCode":200}')

    monkeypatch.setattr(zyte_source.urllib.request, "urlopen", open_request)
    with pytest.raises(UsitcEdisSourceError) as raised:
        edis_credentialed.credentialed_download(
            DOWNLOAD_URL, token=target, max_bytes=1024, timeout_seconds=9.0, route="zyte"
        )
    formatted = "".join(traceback.format_exception(raised.value))
    assert target not in str(raised.value) and proxy not in str(raised.value)
    assert target not in formatted and proxy not in formatted
    assert all(error.closed for error in provider_errors)


def test_missing_zyte_credential_starts_a_new_conservatively_charged_operation(monkeypatch):
    from spicy_docs.sources.zyte import ZyteTransportError

    monkeypatch.setattr(
        edis_credentialed.ZyteHttpFetcher,
        "from_environment",
        classmethod(lambda cls: (_ for _ in ()).throw(ZyteTransportError("missing proxy credential"))),
    )
    monkeypatch.setattr(zyte_source.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no provider request"))
    with EdisAcquirer(budget=BUDGET) as source:
        source.start_external_request(reset_budget=True)
        source.start_external_request()
        with pytest.raises(UsitcEdisSourceError, match="proxy credential") as raised:
            source.acquire_attachment_pdf(DOWNLOAD_URL, token="edis-test-token", credentialed_transport="zyte")
        assert source.request_count == 1
        assert raised.value.usitc_edis_acquisition["requestCount"] == 1


def test_reader_keeps_partial_number_rows_as_evidence_outside_the_docket():
    """The publisher matches a partial number: rows that extend it are evidence, never docket documents."""
    row = INVESTIGATION_337_3673.split(b"<investigations>")[1].split(b"</investigations>")[0]
    investigations = (
        b"<results><investigations>"
        + row.replace(b"337-3673", b"337-1451")
        + row.replace(b"337-3673", b"337-145")
        + b"</investigations></results>"
    )
    retained = DOCUMENTS_337_145_PREFIX.split(b"<documents>")[1].split(b"</documents>")[0]
    first = retained.split(b"</document>")[0] + b"</document>"
    in_scope = (
        first.replace(b"<id>895807</id>", b"<id>895800</id>")
        .replace(b"/attachment/895807", b"/attachment/895800")
        .replace(
            b"<investigationNumber>337-1451</investigationNumber>",
            b"<investigationNumber>337-145</investigationNumber>",
        )
    )
    documents = b"<results><documents>" + in_scope + retained + b"</documents></results>"
    listing = document_list_url(investigation_number="337-145", investigation_phase="Violation")
    routes = {
        investigation_url(number="337-145"): xml_response(investigations),
        listing: xml_response(documents),
        listing.replace("pageNumber=1", "pageNumber=2"): xml_response(EMPTY_DOCUMENTS),
        attachment_url(895800): xml_response(attachment_page(895800)),
    }
    transport = Transport(routes)
    reader = UsitcEdisReader(
        budget=BUDGET, investigation_number="337-145", investigation_phase="Violation", transport=transport
    )
    records = list(reader.iter_records())
    assert [record["documentId"] for record in records] == [895800] and reader.last_keys == ["895800"]
    page_sha = "sha256:" + hashlib.sha256(documents).hexdigest()
    assert reader.partial_match_rows == [
        {
            "investigationNumber": "337-1451",
            "investigationPhase": "Violation",
            "pageSha256": "sha256:" + hashlib.sha256(investigations).hexdigest(),
        },
        {
            "documentId": 895807,
            "investigationNumber": "337-1451",
            "investigationPhase": "Violation",
            "pageSha256": page_sha,
        },
        {
            "documentId": 895798,
            "investigationNumber": "337-1453",
            "investigationPhase": "Violation",
            "pageSha256": page_sha,
        },
        {
            "documentId": 895242,
            "investigationNumber": "337-1454",
            "investigationPhase": "Violation",
            "pageSha256": page_sha,
        },
    ]
    assert [str(call.url) for call in transport.calls if "/attachment/" in str(call.url)] == [attachment_url(895800)]
