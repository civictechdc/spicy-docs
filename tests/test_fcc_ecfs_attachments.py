"""FCC ECFS filing documents read their filings row's declarations and prove their bytes.

The download is a two-host grammar (see the module docstring): docs.fcc.gov
serves FCC-generated files to a direct client, and the www.fcc.gov SPA locator
serves the viewer shell whose own JavaScript reads the file from the plural
byte route ``/ecfs/documents/{id}/{index}``. The acquirer requests each
locator's byte URL through the shared walled-fetch ladder: the DIRECT rung is
the acquirer's own client (an HTTP transport here), and the proxy rungs are
scripted. The refusal kinds, magic checks and identity rules stay the module's
own and stay covered here, all offline.
"""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources import walled_fetch as walled_fetch_module
from spicy_docs.sources.fcc_ecfs_attachments import (
    BROWSER_USER_AGENT,
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_DOCUMENT_REQUESTS,
    DOCS_HOST,
    DOCUMENT_HOST,
    MAX_DOCUMENT_BYTES,
    DeclaredDocument,
    DocumentAcquisition,
    FccDocumentLocator,
    FccEcfsDocumentAcquirer,
    FccEcfsDocumentBudget,
    FccEcfsDocumentError,
    FccEcfsDocumentRefusedError,
    FccEcfsDocumentUnavailableError,
    declared_documents,
    document_locator,
    document_refusal_kind,
    is_spa_shell_body,
)
from spicy_docs.sources.walled_fetch import RungOutcome, Transport, WalledFetchResult, detect_spa_shell
from spicy_docs.transport import capture as capture_module
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures"
FILINGS = json.loads((FIXTURES / "listings" / "fcc-ecfs-filings.json").read_bytes())
DOCUMENT_FILING = next(filing for filing in FILINGS["filing"] if filing.get("documents"))
EXPRESS_FILING = next(filing for filing in FILINGS["filing"] if not filing.get("documents"))
# Real publisher bytes already retained for the regulations.gov attachment
# route; the check under test is format, not provenance.
PDF = (FIXTURES / "regulations_gov_attachments" / "FAA-2016-6907-0001-content.pdf").read_bytes()
DOCX = b"PK\x03\x04rest of a zip container"
OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest of a legacy office file"
BUDGET = FccEcfsDocumentBudget(DEFAULT_MAX_DOCUMENT_REQUESTS, DEFAULT_MAX_DOCUMENT_BYTES, 7, 0)
SUBMISSION = "26110074740"
FILENAME = "ATT Legacy Wireline NG911 Waiver Petition 090126.pdf"
DOCUMENT_URL = f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1"
#: The URL the viewer shell's own JavaScript calls for the file bytes
#: (measured live 2026-09-24, receipt fcc-ecfs-spa-route-2026-09-24); the
#: acquirer requests it instead of the shell-serving locator above.
DOCUMENT_BYTE_URL = f"https://{DOCUMENT_HOST}/ecfs/documents/{SUBMISSION}/1"
PDF_FILENAME = "DA-26-1030A1.pdf"
PDF_URL = f"https://{DOCS_HOST}/public/attachments/{PDF_FILENAME}"
# The SPA host's rejected-client refusal, verbatim from the live 2026-09-24
# capture. Its reference id changes per request, so no instance of it is a digest
# pin; the classification reads the text every instance carries.
AKAMAI_BLOCK = (
    b"<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\n \n"
    b"You don't have permission to access \"http&#58;&#47;&#47;www&#46;fcc&#46;gov&#47;ecfs&#47;document&#47;"
    b'26110074740&#47;1" on this server.<P>\n'
    b"Reference&#32;&#35;18&#46;16643017&#46;1790268796&#46;e2ef3486\n"
    b"<P>https&#58;&#47;&#47;errors&#46;edgesuite&#46;net&#47;18&#46;16643017&#46;1790268796&#46;e2ef3486</P>\n"
    b"</BODY>\n</HTML>\n"
)
# The viewer shell's telltale, synthesized to the markers the module reads; the
# live shell is retained only as a receipt prefix, so this is the smallest body
# that exercises the named refusal.
SPA_SHELL = (
    b'<!doctype html><html lang="en"><head><meta charset="utf-8"/></head>'
    b'<body><div id="root"></div><script src="static/js/main.js"></script></body></html>'
)


@pytest.fixture(autouse=True)
def offline_proxies(monkeypatch):
    """Proxy rungs resolve offline and fail the test unless it scripts them."""
    resolved = walled_fetch_module.ProxyFetchers(zyte=object(), firecrawl=object())
    monkeypatch.setattr(walled_fetch_module.ProxyFetchers, "from_environment", classmethod(lambda _cls: resolved))
    for rung in ("_zyte_rung", "_firecrawl_rung"):
        monkeypatch.setattr(walled_fetch_module, rung, lambda *_a, **_k: pytest.fail("unexpected proxy rung"))


class Direct(httpx.MockTransport):
    """The acquirer's own client for the DIRECT rung: one fixed answer, every request recorded."""

    def __init__(self, body=b"", *, status=200, content_type="application/pdf", error=None):
        self.calls = []

        def handle(request):
            self.calls.append(request)
            if error is not None:
                raise error
            return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})

        super().__init__(handle)


def proxy(monkeypatch, rung, answer):
    """Script one proxy rung with a ladder answer, or a function of the URL returning one; return its URLs."""
    calls = []

    def fetch(url, **_kwargs):
        calls.append(url)
        return answer(url) if callable(answer) else answer

    monkeypatch.setattr(walled_fetch_module, rung, fetch)
    return calls


def result(body, *, status=200, content_type="application/pdf", final_url, transport=Transport.ZYTE_HTTP):
    """One clean proxy answer, exactly the shape a ladder rung returns."""
    request_id = None if transport is Transport.DIRECT else "req-1"
    return WalledFetchResult(body, status, content_type, final_url, transport, None, request_id)


def acquire(direct, target, **kwargs):
    with FccEcfsDocumentAcquirer(budget=BUDGET, transport=direct) as source:
        return source.acquire(target, **kwargs)


def test_the_pinned_filing_declares_one_pdf_document_and_the_express_comment_declares_none():
    declared = declared_documents(DOCUMENT_FILING)
    assert [file.locator.filename for file in declared] == [FILENAME]
    locator = declared[0].locator
    assert locator.url == DOCUMENT_URL and locator.id_submission == SUBMISSION
    assert locator.byte_url == DOCUMENT_BYTE_URL, "the SPA locator names the plural byte route, not itself"
    assert locator.document_index == 1 and locator.extension == "pdf"
    assert locator.dedupe_key == (SUBMISSION, 1) and locator.subject == f"{SUBMISSION}/1"
    assert declared[0].description == ""
    assert declared_documents(EXPRESS_FILING) == ()


def test_locator_keeps_the_publishers_spelling_and_reads_the_extension_from_the_filename():
    locator = document_locator(f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/12", "Petition.PDF")
    assert locator.document_index == 12 and locator.extension == "pdf"
    bare = document_locator(f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/3", "no-extension")
    assert bare.extension is None
    pdf = document_locator(PDF_URL, PDF_FILENAME)
    assert pdf.document_index is None and pdf.extension == "pdf"
    assert pdf.id_submission is None and pdf.dedupe_key == PDF_FILENAME and pdf.subject == PDF_FILENAME
    assert pdf.byte_url == PDF_URL, "a docs.fcc.gov locator serves its file directly"
    encoded = document_locator(f"https://{DOCS_HOST}/public/attachments/ATT%20Petition.pdf", "ATT Petition.pdf")
    assert encoded.filename == "ATT Petition.pdf" and encoded.dedupe_key == "ATT Petition.pdf"


def test_a_docs_fcc_gov_declaration_is_identified_by_its_filename():
    row = {
        "id_submission": SUBMISSION,
        "documents": [
            {"src": PDF_URL, "filename": PDF_FILENAME},
            {"src": f"https://{DOCS_HOST}/public/attachments/DA-26-1030A2.pdf", "filename": "DA-26-1030A2.pdf"},
        ],
    }
    declared = declared_documents(row)
    assert [file.locator.dedupe_key for file in declared] == [PDF_FILENAME, "DA-26-1030A2.pdf"]
    assert all(file.locator.id_submission == SUBMISSION for file in declared)


@pytest.mark.parametrize(
    "src,filename,id_submission,message",
    [
        (None, "a.pdf", None, "HTTPS"),
        (f"http://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1", "a.pdf", None, "HTTPS"),
        ("https://example.gov/ecfs/document/1/1", "a.pdf", None, "HTTPS"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1?x=1", "a.pdf", None, "query"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1#f", "a.pdf", None, "fragment"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}", "a.pdf", None, "path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1/2", "a.pdf", None, "path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/not-digits/1", "a.pdf", None, "path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/0", "a.pdf", None, "path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1", "../x.pdf", None, "name, not a path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1", "dir/x.pdf", None, "name, not a path"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1", " ", None, "no filename"),
        (f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/1", "a.pdf", "999", "different id_submission"),
        (f"http://{DOCS_HOST}/public/attachments/a.pdf", "a.pdf", None, "HTTPS"),
        (f"https://{DOCS_HOST}/public/attachments/a.pdf?x=1", "a.pdf", None, "query"),
        (f"https://{DOCS_HOST}/public/attachments/a.pdf#f", "a.pdf", None, "fragment"),
        (f"https://{DOCS_HOST}/public/attachments/", "a.pdf", None, "path"),
        (f"https://{DOCS_HOST}/attachments/a.pdf", "a.pdf", None, "path"),
        (f"https://{DOCS_HOST}/public/attachments/a%2Fb.pdf", "a.pdf", None, "name, not a path"),
        (f"https://{DOCS_HOST}/public/attachments/other.pdf", "a.pdf", None, "differs from its documents"),
    ],
)
def test_locator_refusals_name_the_failed_check(src, filename, id_submission, message):
    with pytest.raises(FccEcfsDocumentError, match=message):
        document_locator(src, filename, id_submission=id_submission)


@pytest.mark.parametrize(
    "row,message",
    [
        ({}, "no id_submission"),
        ({"id_submission": " "}, "no id_submission"),
        ({"id_submission": SUBMISSION, "documents": {}}, "array or null"),
        ({"id_submission": SUBMISSION, "documents": ["x"]}, "must be an object"),
        ({"id_submission": SUBMISSION, "documents": [{"src": DOCUMENT_URL, "filename": None}]}, "no filename"),
        (
            {"id_submission": SUBMISSION, "documents": [{"src": DOCUMENT_URL, "filename": "a.pdf", "description": 7}]},
            "text or null",
        ),
        (
            {
                "id_submission": SUBMISSION,
                "documents": [
                    {"src": DOCUMENT_URL, "filename": "a.pdf"},
                    {"src": DOCUMENT_URL, "filename": "b.pdf"},
                ],
            },
            "repeats",
        ),
        (
            {
                "id_submission": SUBMISSION,
                "documents": [
                    {"src": PDF_URL, "filename": PDF_FILENAME},
                    {"src": PDF_URL, "filename": PDF_FILENAME},
                ],
            },
            "repeats",
        ),
    ],
)
def test_declaration_refusals_name_the_failed_check(row, message):
    with pytest.raises(FccEcfsDocumentError, match=message):
        declared_documents(row)


def test_a_pinned_pdf_is_proved_by_magic_final_url_and_digest():
    direct = Direct(PDF)
    acquisition = acquire(direct, DeclaredDocument(document_locator(DOCUMENT_URL, FILENAME), ""))
    assert acquisition.capture.body == PDF and acquisition.requested_empty is False
    assert acquisition.capture.requested_url == DOCUMENT_BYTE_URL
    assert acquisition.sha256 == "sha256:f4494ea77d0f8a0ec0b6e7f64e20c6ffe6c53d3be47cd59245f42f74036a7fc0"
    assert acquisition.capture.byte_size == 2620 and PDF.startswith(b"%PDF-")
    assert acquisition.request_count == 1 and acquisition.budget == BUDGET
    assert acquisition.transport is Transport.DIRECT and acquisition.request_id is None
    # The host is keyless; the direct rung asks the byte route with the carried-over agent.
    assert [str(request.url) for request in direct.calls] == [DOCUMENT_BYTE_URL]
    assert direct.calls[0].headers["User-Agent"] == BROWSER_USER_AGENT


def test_a_docs_fcc_gov_pdf_is_acquired_directly_and_proved_by_its_magic():
    direct = Direct(PDF)
    acquisition = acquire(direct, document_locator(PDF_URL, PDF_FILENAME))
    assert acquisition.capture.body == PDF and acquisition.requested_empty is False
    assert acquisition.locator.dedupe_key == PDF_FILENAME
    assert acquisition.request_count == 1
    assert str(direct.calls[0].url) == PDF_URL


def test_a_clean_answer_from_a_later_rung_records_its_transport_and_every_charged_attempt(monkeypatch):
    zyte = proxy(monkeypatch, "_zyte_rung", RungOutcome(Transport.ZYTE_HTTP, "wall", body=AKAMAI_BLOCK))
    proxy(monkeypatch, "_firecrawl_rung", lambda url: result(PDF, final_url=url, transport=Transport.FIRECRAWL_RAW))
    acquisition = acquire(
        Direct(AKAMAI_BLOCK, status=403, content_type="text/html"), document_locator(DOCUMENT_URL, FILENAME)
    )
    assert acquisition.capture.body == PDF and zyte == [DOCUMENT_BYTE_URL]
    assert acquisition.transport is Transport.FIRECRAWL_RAW and acquisition.request_id == "req-1"
    assert acquisition.request_count == 3, "proxy rungs are charged on the same budget as the direct attempt"


def test_every_rung_is_paced_on_the_acquirers_own_clock(monkeypatch):
    elapsed, sleeps = [0.0], []

    def sleep(delay):
        sleeps.append(delay)
        elapsed[0] += delay

    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", sleep)
    started = []

    def zyte(url):
        started.append(elapsed[0])
        return result(PDF, final_url=url)

    proxy(monkeypatch, "_zyte_rung", zyte)
    budget = FccEcfsDocumentBudget(DEFAULT_MAX_DOCUMENT_REQUESTS, DEFAULT_MAX_DOCUMENT_BYTES, 7, 5)
    direct = Direct(AKAMAI_BLOCK, status=403, content_type="text/html")
    with FccEcfsDocumentAcquirer(budget=budget, transport=direct) as source:
        counts = [source.acquire(document_locator(DOCUMENT_URL, FILENAME)).request_count for _ in range(2)]
    assert counts == [2, 2] and started == [5, 15] and sleeps == [5, 5, 5]


def test_the_request_bound_stops_the_ladder_before_the_next_rung():
    direct = Direct(AKAMAI_BLOCK, status=403, content_type="text/html")
    budget = FccEcfsDocumentBudget(1, DEFAULT_MAX_DOCUMENT_BYTES, 7, 0)
    with (
        FccEcfsDocumentAcquirer(budget=budget, transport=direct) as source,
        pytest.raises(FccEcfsDocumentRefusedError) as raised,
    ):
        source.acquire(document_locator(DOCUMENT_URL, FILENAME))
    assert len(direct.calls) == 1 and raised.value.fcc_ecfs_document_acquisition["requestCount"] == 1
    assert raised.value.refusal_kind == "client-rejected"


@pytest.mark.parametrize(
    "filename,body,content_type",
    [
        ("filing.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("filing.doc", OLE2, "application/octet-stream"),
        ("filing.zip", DOCX, "application/force-download"),
        ("filing.txt", b"plain text body", "text/plain"),
        ("no-extension", b"any bytes at all", "application/octet-stream"),
        ("filing.pdf", PDF, "application/octet-stream"),
    ],
)
def test_other_declared_formats_are_proved_by_their_extension_magic_or_recorded_without_one(
    filename, body, content_type
):
    url = f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/2"
    acquisition = acquire(Direct(body, content_type=content_type), document_locator(url, filename))
    assert acquisition.capture.body == body and acquisition.requested_empty is False


def test_a_file_carrying_its_formats_magic_is_never_read_as_a_wall():
    # Block-page chrome inside a real container must not escalate or abort the run.
    body = DOCX + b" quoted: You don't have permission to access"
    url = f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/2"
    acquisition = acquire(Direct(body, content_type="application/octet-stream"), document_locator(url, "f.docx"))
    assert acquisition.capture.body == body and acquisition.transport is Transport.DIRECT


@pytest.mark.parametrize(
    "filename,body,content_type,message",
    [
        ("filing.pdf", DOCX, "application/pdf", "does not begin with the %PDF- magic"),
        ("filing.pdf", b"%PDF-1.4 cut off without a trailer", "application/pdf", "does not end with a PDF trailer"),
        (
            "filing.docx",
            OLE2,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "magic its docx filename declares",
        ),
        ("filing.doc", DOCX, "application/msword", "magic its doc filename declares"),
    ],
)
def test_magic_mismatches_name_the_filename_that_lied(filename, body, content_type, message):
    url = f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/2"
    with pytest.raises(FccEcfsDocumentError) as raised:
        acquire(Direct(body, content_type=content_type), document_locator(url, filename))
    assert message in str(raised.value)
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.fcc_ecfs_document_acquisition["idSubmission"] == SUBMISSION


def test_a_requested_empty_answer_is_recorded_not_skipped():
    acquisition = acquire(Direct(b""), document_locator(DOCUMENT_URL, FILENAME))
    assert isinstance(acquisition, DocumentAcquisition) and acquisition.requested_empty is True
    assert acquisition.capture.byte_size == 0 and acquisition.capture.body == b""


def test_an_html_media_type_is_refused_whatever_the_extension():
    direct = Direct(PDF, content_type="text/html")
    with pytest.raises(FccEcfsDocumentError, match="Content-Type differs") as raised:
        acquire(direct, document_locator(DOCUMENT_URL, FILENAME))
    assert not isinstance(raised.value, CredentialRefusedError)
    assert direct.calls[0].headers["User-Agent"] == BROWSER_USER_AGENT


def test_the_akamai_refusal_is_classified_by_its_text_because_its_digest_changes_per_request():
    body = Path.home().joinpath(
        "Work/corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-24/q1-fcc-ecfs-document-host",
        "03-browser-agent-accept-headers.body",
    )
    if not body.exists():
        pytest.skip(f"retained capture not present: {body}")
    retained = body.read_bytes()
    assert retained == AKAMAI_BLOCK and len(retained) == 404
    assert document_refusal_kind(retained) == "client-rejected"
    for other in (b"", None, b"<html>403 Forbidden</html>", b'{"message":"Forbidden"}'):
        assert document_refusal_kind(other) == "unrecognized"


def test_a_ladder_wall_names_the_akamai_rejection_aborts_and_never_establishes_absence(monkeypatch):
    for rung, transport in (("_zyte_rung", Transport.ZYTE_HTTP), ("_firecrawl_rung", Transport.FIRECRAWL_RAW)):
        proxy(monkeypatch, rung, RungOutcome(transport, "wall", body=b"<html>Access Denied</html>"))
    with pytest.raises(FccEcfsDocumentRefusedError) as raised:
        acquire(Direct(AKAMAI_BLOCK, status=403, content_type="text/html"), document_locator(DOCUMENT_URL, FILENAME))
    # A refusal still ends the operation: callers that abort on one keep aborting.
    assert isinstance(raised.value, CredentialRefusedError)
    assert raised.value.refusal_kind == "client-rejected" and "rejected this client" in str(raised.value)
    assert "not an observation that the file is absent" in str(raised.value)
    assert raised.value.locator.dedupe_key == (SUBMISSION, 1)
    assert raised.value.refused_response.response_bytes == AKAMAI_BLOCK, "the first wall's exact bytes"
    assert raised.value.fcc_ecfs_document_acquisition["filename"] == FILENAME
    assert raised.value.fcc_ecfs_document_acquisition["requestCount"] == 3
    assert [outcome.kind for outcome in raised.value.rung_outcomes] == ["wall", "wall", "wall"]
    assert not hasattr(raised.value, "capture"), "a refusal is not a capture"


def test_every_rung_answering_401_403_without_markers_is_a_refusal_in_no_known_shape(monkeypatch):
    for rung, transport in (("_zyte_rung", Transport.ZYTE_HTTP), ("_firecrawl_rung", Transport.FIRECRAWL_RAW)):
        proxy(monkeypatch, rung, RungOutcome(transport, "publisher-refused"))
    with pytest.raises(FccEcfsDocumentRefusedError) as raised:
        acquire(Direct(b"Forbidden", status=403, content_type="text/plain"), document_locator(DOCUMENT_URL, FILENAME))
    assert raised.value.refusal_kind == "unrecognized" and "no shape" in str(raised.value)
    assert raised.value.refused_response.unavailable_reason == "publisher-refused"


def test_rungs_that_never_reached_a_publisher_are_not_a_refusal(monkeypatch):
    for rung, transport in (("_zyte_rung", Transport.ZYTE_HTTP), ("_firecrawl_rung", Transport.FIRECRAWL_RAW)):
        proxy(monkeypatch, rung, RungOutcome(transport, "transport-error", detail="connection reset"))
    with pytest.raises(FccEcfsDocumentError) as raised:
        acquire(Direct(error=httpx.ConnectError("connection reset")), document_locator(DOCUMENT_URL, FILENAME))
    assert not isinstance(raised.value, CredentialRefusedError), "a transport failure is not a publisher answer"
    assert [outcome.kind for outcome in raised.value.rung_outcomes] == ["transport-error"] * 3
    assert raised.value.fcc_ecfs_document_acquisition["idSubmission"] == SUBMISSION


def test_the_spa_shell_is_a_named_refusal_not_the_file():
    # text/html is never an accepted document media type; the shell wins its own
    # name instead of falling through to the Content-Type refusal.
    direct = Direct(SPA_SHELL, content_type="text/html")
    with pytest.raises(FccEcfsDocumentRefusedError) as raised:
        acquire(direct, document_locator(DOCUMENT_URL, FILENAME))
    assert raised.value.refusal_kind == "spa-shell"
    assert "answered the viewer shell instead of the file" in str(raised.value)
    assert "not an observation that the file is absent" in str(raised.value)
    assert raised.value.refused_response.response_bytes == SPA_SHELL
    assert raised.value.fcc_ecfs_document_acquisition["documentIndex"] == 1
    assert raised.value.fcc_ecfs_document_acquisition["url"] == DOCUMENT_URL
    assert raised.value.fcc_ecfs_document_acquisition["requestUrl"] == DOCUMENT_BYTE_URL
    assert not hasattr(raised.value, "capture"), "a refusal is not a capture"
    assert [str(request.url) for request in direct.calls] == [DOCUMENT_BYTE_URL], "a clean shell does not escalate"


@pytest.mark.parametrize(
    "body,content_type,expected",
    [
        (b'<div id="root"></div>', "text/html", True),
        (b'<!doctype html><html><body><div id="root"></div></body></html>', "text/html; charset=utf-8", True),
        (b"You need to enable JavaScript to run this app.", "text/html", True),
        (b'<div id="root"></div>You don\'t have permission to access', "text/html", False),
        (b'<div id="root"></div>', "application/pdf", False),
        (b"%PDF-1.4", "text/html", False),
        (b"<html>plain page</html>", "text/html", False),
    ],
)
def test_the_spa_shell_check_reads_the_media_type_the_markers_and_never_a_wall(body, content_type, expected):
    assert is_spa_shell_body(body, content_type) is expected


def test_the_spa_shell_check_delegates_to_the_canonical_ladder_vocabulary():
    # Boyscout: the route owns the media-type gate, and the ladder module owns
    # the shell vocabulary; the two must agree byte for byte.
    shell = b'<div id="root"></div>'
    assert detect_spa_shell(shell) is True
    assert is_spa_shell_body(shell, "text/html") is True
    assert is_spa_shell_body(shell, "application/pdf") is False
    assert is_spa_shell_body(b"You need to enable JavaScript to run this app.", "text/html") is True
    assert is_spa_shell_body(b'<div id="root"></div>Access Denied', "text/html") is False


def test_a_redirect_answer_is_a_named_refusal_not_a_followed_one(monkeypatch):
    moved = b"<html>moved</html>"
    zyte = proxy(
        monkeypatch,
        "_zyte_rung",
        lambda url: result(moved, content_type="text/html", final_url="https://elsewhere.gov/f.pdf"),
    )
    with pytest.raises(FccEcfsDocumentRefusedError) as raised:
        acquire(Direct(AKAMAI_BLOCK, status=403, content_type="text/html"), document_locator(DOCUMENT_URL, FILENAME))
    assert raised.value.refusal_kind == "redirected"
    assert "states nothing about the file existing" in str(raised.value)
    assert raised.value.refused_response.response_bytes == moved
    assert zyte == [DOCUMENT_BYTE_URL], "the refusal names the byte route's redirect, and nothing escalates past it"


@pytest.mark.parametrize("status", [404, 410])
def test_only_404_and_410_say_the_exact_url_has_nothing(status):
    with pytest.raises(FccEcfsDocumentUnavailableError) as missing:
        acquire(Direct(b"", status=status, content_type="application/json"), document_locator(DOCUMENT_URL, FILENAME))
    assert missing.value.capture.status_code == status


def test_configuration_is_explicit_and_bad_input_spends_no_request():
    direct = Direct()
    with FccEcfsDocumentAcquirer(budget=BUDGET, transport=direct) as source:
        with pytest.raises(TypeError):
            source.acquire(DOCUMENT_URL)
        with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
            source.acquire(document_locator(DOCUMENT_URL, FILENAME), max_bytes=0)
    assert direct.calls == []
    for fields in ({"max_requests": 0}, {"max_bytes": MAX_DOCUMENT_BYTES + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            FccEcfsDocumentBudget(
                **{
                    "max_requests": DEFAULT_MAX_DOCUMENT_REQUESTS,
                    "max_bytes": DEFAULT_MAX_DOCUMENT_BYTES,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        FccEcfsDocumentAcquirer(budget=(DEFAULT_MAX_DOCUMENT_REQUESTS, DEFAULT_MAX_DOCUMENT_BYTES, 7, 0))
    with pytest.raises(ValueError, match="user_agent"):
        FccEcfsDocumentAcquirer(budget=BUDGET, user_agent=" ")


def test_a_fresh_locator_can_be_acquired_without_a_declared_description():
    locator = document_locator(f"https://{DOCUMENT_HOST}/ecfs/document/{SUBMISSION}/7", "h.docx")
    assert isinstance(locator, FccDocumentLocator) and locator.dedupe_key == (SUBMISSION, 7)
    assert locator.byte_url == f"https://{DOCUMENT_HOST}/ecfs/documents/{SUBMISSION}/7"
    acquisition = acquire(Direct(DOCX, content_type="application/octet-stream"), locator)
    assert acquisition.locator is locator and acquisition.capture.body == DOCX
