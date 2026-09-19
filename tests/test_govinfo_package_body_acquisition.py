"""Acquire one GovInfo package body over real HTTPX streams, offline.

The three CRPT-119hrpt1 fixtures are exact publisher responses; every refusal
case is synthetic. The live case is marked ``integration`` and skipped without
a credential file.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources.govinfo.bodies import BODY_PREFERENCE, GovInfoBodySourceError
from spicy_docs.sources.govinfo.body_acquisition import (
    GovInfoBodyAcquirer,
    GovInfoBodyBudget,
    GovInfoFormatNotOfferedError,
    GovInfoPackageBody,
    GovInfoPackageUnavailableError,
    GovInfoRenditionAddressError,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key

from .test_govinfo_package_bodies import BODY, MODS, SUMMARY, mods_xml

PACKAGE = "CRPT-119hrpt1"
SUMMARY_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/summary"
MODS_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/mods"
HTM_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{PACKAGE}.htm"
PDF_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf"
KEY = "test-credential-0123456789"
BUDGET = GovInfoBodyBudget(
    max_requests=4,
    max_body_bytes=1024 * 1024,
    max_metadata_bytes=1024 * 1024,
    timeout_seconds=7.0,
    min_request_interval_seconds=0,
)
NOW = datetime(2026, 9, 19, tzinfo=UTC)
ENV_FILE = Path(os.environ.get("SPICY_DOCS_ENV_FILE", Path.home() / "Work/spicy-stack/spicy-docs/.env"))


class Stream(httpx.SyncByteStream):
    """A fresh stream per call; the client reads raw bytes through to EOF."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __iter__(self):
        yield self.body


def reply(body: bytes, *, status: int = 200, content_type: str | None = None, location: str | None = None):
    headers = {}
    if content_type is not None:
        headers["content-type"] = content_type
    if location is not None:
        headers["location"] = location
    # GovInfo streams its HTML without a Content-Length, so these do too.
    return lambda: httpx.Response(status, stream=Stream(body), headers=headers)


JSON_SUMMARY = reply(SUMMARY, content_type="application/json")
XML_MODS = reply(MODS, content_type="application/xml")
HTML_BODY = reply(BODY, content_type="text/html")


class Transport(httpx.MockTransport):
    """Answer by URL so a test reads as the routes it expects to be called."""

    def __init__(self, **routes) -> None:
        self.routes = {SUMMARY_URL: JSON_SUMMARY, MODS_URL: XML_MODS, HTM_URL: HTML_BODY} | routes
        self.calls: list[httpx.Request] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get(str(request.url))
        if route is None:
            raise AssertionError(f"unexpected request {request.url}")
        return route()

    @property
    def urls(self) -> list[str]:
        return [str(call.url) for call in self.calls]


def acquire(transport: Transport, **arguments) -> GovInfoPackageBody:
    budget = arguments.pop("budget", BUDGET)
    with GovInfoBodyAcquirer(budget=budget, api_key=KEY, transport=transport, clock=lambda: NOW) as client:
        return client.acquire(arguments.pop("package_id", PACKAGE), **arguments)


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_acquires_the_first_offered_preferred_format_with_every_capture() -> None:
    transport = Transport()
    result = acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert result.request_count == 3
    assert result.format == "htm"
    assert result.preference == BODY_PREFERENCE == ("xml", "htm", "txt", "pdf")
    # The publisher offers no XML for a committee report, so the second
    # preference is taken; the summary states no body rendition at all.
    assert result.offered_formats == ("htm", "pdf")
    assert result.mods.access_ids == (PACKAGE, PACKAGE)
    assert result.mods.moved_renditions == ()
    assert result.body.byte_size == len(BODY)
    assert result.body_capture.body == BODY
    assert [capture.status_code for capture in result.captures] == [200, 200, 200]
    assert [capture.observed_at for capture in result.captures] == ["2026-09-19T00:00:00Z"] * 3
    assert [capture.resolved_url for capture in result.captures] == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert result.body_capture.content_type == "text/html"
    assert result.body_capture.sha256.startswith("sha256:")
    assert result.budget == BUDGET


def test_the_credential_travels_only_to_the_keyed_routes() -> None:
    transport = Transport()
    acquire(transport)

    keyed, keyless = transport.calls[:2], transport.calls[2]
    assert all(call.headers["x-api-key"] == KEY for call in keyed)
    assert "x-api-key" not in keyless.headers
    assert all("api_key" not in str(call.url) for call in transport.calls)
    assert all("authorization" not in call.headers for call in transport.calls)


def test_pdf_is_reached_when_the_caller_names_it() -> None:
    transport = Transport(**{PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf")})
    result = acquire(transport, prefer=("pdf",))

    assert transport.urls[-1] == PDF_URL
    assert result.format == "pdf" and result.body.media_type == "application/pdf"


def test_pdf_is_last_under_the_default_so_an_offered_text_rendition_wins() -> None:
    """The sealed order ends in PDF, but only reaches it when nothing earlier is offered."""
    transport = Transport(**{PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf")})
    result = acquire(transport)

    assert BODY_PREFERENCE[-1] == "pdf"
    assert result.offered_formats == ("htm", "pdf")
    assert result.format == "htm"
    assert PDF_URL not in transport.urls


def test_a_pdf_only_package_yields_a_body_under_the_default() -> None:
    """The ruling this seals: CREC offers PDF alone, and the old default refused it."""
    pdf_only = f'<url displayLabel="PDF rendition" access="raw object">{PDF_URL}</url>'
    transport = Transport(
        **{
            MODS_URL: reply(mods_xml(urls=pdf_only), content_type="application/xml"),
            PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf"),
        }
    )
    result = acquire(transport)

    assert result.offered_formats == ("pdf",)
    assert result.format == "pdf"
    # The previous default stopped at txt, so this exact package refused.
    with pytest.raises(GovInfoFormatNotOfferedError):
        acquire(transport, prefer=("xml", "htm", "txt"))


def test_a_pdf_without_its_magic_is_refused_with_its_bytes() -> None:
    transport = Transport(**{PDF_URL: reply(b"<html>not a pdf</html>", content_type="application/pdf")})
    with pytest.raises(GovInfoBodySourceError, match="%PDF-") as caught:
        acquire(transport, prefer=("pdf",))

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == b"<html>not a pdf</html>" and refusal.stage == "source-validation"
    assert caught.value.__dict__["govinfo_body_acquisition"]["stage"] == "body"


def test_a_format_the_package_does_not_offer_refuses_before_any_body_request() -> None:
    transport = Transport()
    with pytest.raises(GovInfoFormatNotOfferedError, match="none matches") as caught:
        acquire(transport, prefer=("xml", "txt"))

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.offered_formats == ("htm", "pdf")
    context = caught.value.__dict__["govinfo_body_acquisition"]
    assert context["stage"] == "mods" and context["format"] is None
    assert context["offeredFormats"] == ["htm", "pdf"]
    assert context["requestCount"] == 2


def test_a_preferred_format_stated_elsewhere_refuses_as_disagreement() -> None:
    uslm = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/uslm/{PACKAGE}.xml"
    renditions = f'<url displayLabel="USLM rendition" access="raw object">{uslm}</url>'
    transport = Transport(**{MODS_URL: reply(mods_xml(urls=renditions), content_type="application/xml")})
    with pytest.raises(GovInfoRenditionAddressError, match="not where this module fetches it") as caught:
        acquire(transport, prefer=("xml",))

    # The package does state XML; it states it somewhere this module does not
    # derive, which is a different answer from "no XML rendition exists".
    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.moved_renditions == (("xml", uslm),)
    assert uslm in str(caught.value)


def test_a_missing_package_is_unavailable_not_absent() -> None:
    missing = reply(b'{"message":"The requested resource does not exist."}', status=404, content_type="text/plain")
    transport = Transport(**{SUMMARY_URL: missing})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 404") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL]
    assert caught.value.capture.status_code == 404
    assert caught.value.__dict__["refused_response"].response_bytes is not None


def test_a_redirected_rendition_is_unavailable_and_never_followed() -> None:
    # Measured: an absent or unoffered rendition answers 302 to /error, which
    # itself answers 200. Following it would turn absence into a body.
    transport = Transport(**{HTM_URL: reply(b"", status=302, location="https://www.govinfo.gov/error")})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 302") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert caught.value.capture.resolved_url == HTM_URL


def test_the_error_page_served_as_a_body_is_refused_with_its_bytes() -> None:
    page = b'<html><a href="https://www.govinfo.gov/error">Page Not Found</a></html>'
    transport = Transport(**{HTM_URL: reply(page, content_type="text/html")})
    with pytest.raises(GovInfoBodySourceError, match="error page") as caught:
        acquire(transport)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == page and refusal.request_key == HTM_URL


def test_a_body_in_another_format_is_refused() -> None:
    transport = Transport(**{HTM_URL: reply(BODY, content_type="application/pdf")})
    with pytest.raises(GovInfoBodySourceError, match="Content-Type"):
        acquire(transport)


def test_a_mods_access_id_for_another_package_refuses_before_the_body() -> None:
    transport = Transport(**{MODS_URL: reply(mods_xml(access_id="CRPT-119hrpt2"), content_type="application/xml")})
    with pytest.raises(GovInfoBodySourceError, match="accessId differs") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.__dict__["refused_response"].request_key == MODS_URL


def test_a_summary_for_another_package_refuses_before_the_mods() -> None:
    other = SUMMARY.replace(b'"packageId": "CRPT-119hrpt1"', b'"packageId": "CRPT-119hrpt2"')
    transport = Transport(**{SUMMARY_URL: reply(other, content_type="application/json")})
    with pytest.raises(GovInfoBodySourceError, match="packageId differs"):
        acquire(transport)


@pytest.mark.parametrize("status", [401, 403])
def test_a_keyed_credential_refusal_aborts_without_retaining_bytes(status: int) -> None:
    transport = Transport(**{SUMMARY_URL: reply(b"credential material", status=status)})
    with pytest.raises(CredentialRefusedError) as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert isinstance(refusal, RefusedResponse) and refusal.response_bytes is None
    assert "capture" not in caught.value.__dict__


def test_a_keyless_wall_keeps_the_publishers_own_answer() -> None:
    wall = b"<html>Access denied by the edge</html>"
    transport = Transport(**{HTM_URL: reply(wall, status=403, content_type="text/html")})
    with pytest.raises(CredentialRefusedError) as caught:
        acquire(transport)

    # The body routes carry no credential, so a 403 there is the publisher's
    # answer and is worth keeping; the keyed routes never retain one.
    assert caught.value.__dict__["refused_response"].response_bytes == wall


def test_a_keyed_response_that_echoes_the_credential_is_refused_unretained() -> None:
    transport = Transport(**{MODS_URL: reply(KEY.encode(), content_type="application/xml")})
    with pytest.raises(CredentialRefusedError, match="echoed"):
        acquire(transport)


def test_both_clients_spend_one_request_budget() -> None:
    transport = Transport()
    with pytest.raises(GovInfoBodySourceError, match="request budget") as caught:
        acquire(transport, budget=replace(BUDGET, max_requests=2))

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == HTM_URL and refusal.stage == "before-request"
    assert refusal.unavailable_reason == "request-budget-exhausted"


def test_a_retry_spends_the_same_budget_as_the_metadata_requests() -> None:
    attempts = iter([reply(b"", status=503), HTML_BODY])
    transport = Transport(**{HTM_URL: lambda: next(attempts)()})
    result = acquire(transport, budget=replace(BUDGET, max_requests=4))

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL, HTM_URL]
    assert result.request_count == 4


def test_a_body_over_its_bound_returns_no_partial_bytes() -> None:
    transport = Transport()
    with pytest.raises(GovInfoBodySourceError, match="byte bound") as caught:
        acquire(transport, max_bytes=len(BODY) - 1)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes is None and refusal.unavailable_reason == "response-byte-limit"
    assert caught.value.__dict__["govinfo_body_acquisition"]["budget"]["max_body_bytes"] == len(BODY) - 1


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"package_id": "CRPT-GPO-J6-REPORT"}, GovInfoBodySourceError),
        ({"package_id": "PPP-2026-01-02"}, GovInfoBodySourceError),
        ({"prefer": ()}, ValueError),
        ({"prefer": ("htm", "htm")}, ValueError),
        ({"prefer": ("uslm",)}, ValueError),
        ({"prefer": "htm"}, TypeError),
        ({"max_bytes": 0}, ValueError),
    ],
)
def test_invalid_selections_refuse_before_any_request(arguments: dict, error: type[Exception]) -> None:
    transport = Transport()
    with pytest.raises(error):
        acquire(transport, **arguments)
    assert not transport.calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_requests", 0),
        ("max_body_bytes", 0),
        ("max_metadata_bytes", 24 * 1024 * 1024 + 1),
        ("timeout_seconds", 0),
        ("min_request_interval_seconds", -1),
    ],
)
def test_invalid_budget_refused(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        replace(BUDGET, **{field: value})


def test_an_acquirer_without_a_credential_refuses_to_exist() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GovInfoBodyAcquirer(budget=BUDGET, api_key="", transport=Transport())


def test_a_closed_client_refuses_without_a_request() -> None:
    transport = Transport()
    client = GovInfoBodyAcquirer(budget=BUDGET, api_key=KEY, transport=transport)
    client.close()
    with pytest.raises(ValueError, match="closed"):
        client.acquire(PACKAGE)
    assert not transport.calls


@pytest.mark.integration
@pytest.mark.parametrize("package_id", ["CRPT-119hrpt1", "CHRG-119hhrg64242"])
def test_live_package_body_is_acquired_and_proved(package_id: str) -> None:
    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    budget = GovInfoBodyBudget(
        max_requests=6,
        max_body_bytes=24 * 1024 * 1024,
        max_metadata_bytes=8 * 1024 * 1024,
        timeout_seconds=60.0,
        min_request_interval_seconds=0.5,
    )
    key = read_api_key(ENV_FILE, "API_GOV")
    with GovInfoBodyAcquirer(budget=budget, api_key=key) as client:
        result = client.acquire(package_id)

    assert result.identity.package_id == package_id
    assert result.summary.identity.package_id == package_id
    assert set(result.mods.access_ids) == {package_id}
    # Measured 2026-09-19: both collections offer HTML and PDF, no XML or text.
    assert result.offered_formats == ("htm", "pdf")
    assert result.format == "htm"
    assert result.body_capture.status_code == 200
    assert result.body_capture.byte_size > 1_000
    assert b"govinfo.gov/error" not in result.body_capture.body
    assert key.encode() not in result.body_capture.body
