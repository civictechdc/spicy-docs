"""Publisher text keeps exact bytes and uses the same bounded capture as XML."""

from dataclasses import replace

import httpx
import pytest

from spicy_docs.sources.federal_register.body_acquisition import FederalRegisterBodyAcquirer, FederalRegisterBodyBudget
from spicy_docs.sources.federal_register.body_sources import FederalRegisterBodySourceError, body_source_locators
from spicy_docs.sources.federal_register.body_text import publisher_text_locator, validate_publisher_text
from spicy_docs.transport.credentials import CredentialRefusedError

NUMBER = "98-26796"
DATE = "1998-10-13"
URL = publisher_text_locator(NUMBER, DATE)
BODY = b"<html><body><pre>[FR Doc No: 98-26796]\nList of Subjects\n\nSafety.\n</pre></body></html>"
BUDGET = FederalRegisterBodyBudget(1, 1024, 1024, 5, 0)


def validate(body=BODY, **changes):
    arguments = {"source_document_number": NUMBER, "publication_date": DATE, "final_url": URL, "max_bytes": 1024}
    return validate_publisher_text(body, **(arguments | changes))


def test_locator_agrees_with_source_stated_sibling_path():
    locators = body_source_locators(
        {
            "document_number": NUMBER,
            "publication_date": DATE,
            "body_html_url": URL.replace("/text/", "/html/").removesuffix(".txt") + ".html",
        }
    )
    assert URL == locators.publisher_text_url
    identity = validate()
    assert identity.source_document_number == identity.marker_document_number == NUMBER
    assert identity.publication_date == DATE and identity.match_kind == "exact-source"


def test_split_number_keeps_the_exact_printed_base():
    identity = validate(source_document_number=NUMBER + "-2", final_url=publisher_text_locator(NUMBER + "-2", DATE))
    assert identity.source_document_number == NUMBER + "-2"
    assert identity.marker_document_number == NUMBER and identity.match_kind == "split-base"


@pytest.mark.parametrize(
    "body", [b"", b"Access denied", b"[FR Doc No: 98-267960]", b"[FR Doc. 98-26796 Filed yesterday]"]
)
def test_absent_or_wrong_header_is_refused(body):
    with pytest.raises(FederalRegisterBodySourceError, match="document marker"):
        validate(body)


@pytest.mark.parametrize(
    "changes",
    [
        {"final_url": URL + "?different=1"},
        {"final_url": URL.replace("1998/10/13", "1998/10/14")},
        {"publication_date": "1998-10-14"},
        {"source_document_number": "../98-26796"},
        {"max_bytes": 1},
        {"max_bytes": True},
    ],
)
def test_invalid_identity_or_bound_is_refused(changes):
    with pytest.raises(FederalRegisterBodySourceError):
        validate(**changes)


@pytest.mark.parametrize("media_type", ["text/plain", "text/html; charset=utf-8"])
def test_explicit_text_capture_preserves_wrapped_bytes_and_uses_one_request(media_type):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, stream=httpx.ByteStream(BODY), headers={"Content-Type": media_type})

    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=httpx.MockTransport(respond)) as client:
        result = client.acquire(document_number=NUMBER, publication_date=DATE, format="txt")
    assert calls == [URL] and result.request_count == 1
    assert result.requested_format == result.format == "txt" and result.route == "publisher-text"
    assert result.body.body == BODY
    assert result.mods is result.mods_resolution is result.unavailable_xml is None
    assert result.identity == validate()


@pytest.mark.parametrize(
    "status,body,media_type",
    [
        (200, b"<html>Challenge page</html>", "text/html"),
        (200, BODY, "application/pdf"),
        (404, b"Not found", "text/plain"),
        (410, b"Gone", "text/plain"),
        (302, b"Moved", "text/plain"),
    ],
)
def test_failed_text_retains_refused_response_without_format_fallback(status, body, media_type):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(
            status,
            stream=httpx.ByteStream(body),
            headers={"Content-Type": media_type, "Location": "https://example.test"},
        )

    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=httpx.MockTransport(respond)) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        client.acquire(document_number=NUMBER, publication_date=DATE, format="txt")
    assert calls == [URL]
    assert caught.value.refused_response.response_bytes == body
    assert caught.value.body_acquisition["route"] == "publisher-text"
    assert caught.value.body_acquisition["unavailableXml"] is None


@pytest.mark.parametrize("status", [401, 403])
def test_text_access_refusal_aborts(status):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(status, stream=httpx.ByteStream(b"refused"))

    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=httpx.MockTransport(respond)) as client,
        pytest.raises(CredentialRefusedError),
    ):
        client.acquire(document_number=NUMBER, publication_date=DATE, format="txt")
    assert calls == [URL]


def test_text_overflow_never_becomes_complete_evidence():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=httpx.ByteStream(BODY)))
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_body_bytes=8), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        client.acquire(document_number=NUMBER, publication_date=DATE, format="txt")
    assert caught.value.refused_response.response_bytes is None


@pytest.mark.parametrize("options", [{"html_route": "mods-start-page", "start_page": 1}, {"start_page": 1}])
def test_text_refuses_html_selection_arguments_before_any_request(options):
    def unexpected(request):
        raise AssertionError("invalid text selection attempted HTTP")

    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=httpx.MockTransport(unexpected)) as client,
        pytest.raises(ValueError, match="publisher text"),
    ):
        client.acquire(document_number=NUMBER, publication_date=DATE, format="txt", **options)
