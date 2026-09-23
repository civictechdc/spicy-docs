"""Acquire one GovInfo package body over real HTTPX streams, offline.

Pins the sealed preference order and the print permutation, credential scoping
to keyed routes, MODS identity and rendition disagreement, unavailable,
redirect and error-page refusals, shared request budgets, byte bounds, and
one body per part of a multi-part report, all or nothing.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources.govinfo.bodies import BODY_PREFERENCE, PRINT_BODY_PREFERENCE, GovInfoBodySourceError
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

from .test_govinfo_package_bodies import (
    BODY,
    FIXTURES,
    MODS,
    PART,
    PART_MODS,
    PART_PACKAGE,
    PART_SUMMARY,
    SUMMARY,
    mods_xml,
)

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
    """An HTTPX response over the given bytes."""
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
    """Acquire the fixture package through the transport."""
    budget = arguments.pop("budget", BUDGET)
    with GovInfoBodyAcquirer(budget=budget, api_key=KEY, transport=transport, clock=lambda: NOW) as client:
        return client.acquire(arguments.pop("package_id", PACKAGE), **arguments)


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_acquires_the_first_offered_preferred_format_with_every_capture() -> None:
    """Acquisition takes the first offered preferred format, keeping every capture, MODS identity and the sealed
    preference order.
    """
    transport = Transport()
    result = acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert result.request_count == 3
    assert result.format == "htm"
    assert result.preference == BODY_PREFERENCE == ("xml", "uslm", "htm", "txt", "pdf")
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
    """The credential travels only to keyed routes and never in URLs."""
    transport = Transport()
    acquire(transport)

    keyed, keyless = transport.calls[:2], transport.calls[2]
    assert all(call.headers["x-api-key"] == KEY for call in keyed)
    assert "x-api-key" not in keyless.headers
    assert all("api_key" not in str(call.url) for call in transport.calls)
    assert all("authorization" not in call.headers for call in transport.calls)


def test_pdf_is_reached_when_the_caller_names_it() -> None:
    """PDF is reached when the caller names it."""
    transport = Transport(**{PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf")})
    result = acquire(transport, prefer=("pdf",))

    assert transport.urls[-1] == PDF_URL
    assert result.format == "pdf" and result.body.media_type == "application/pdf"


def test_the_print_preference_is_the_sealed_order_with_pdf_moved_to_the_front() -> None:
    """The print preference is a permutation of the sealed order with PDF first, never a different opinion."""
    assert PRINT_BODY_PREFERENCE[0] == "pdf"
    assert sorted(PRINT_BODY_PREFERENCE) == sorted(BODY_PREFERENCE)
    assert PRINT_BODY_PREFERENCE[1:] == tuple(name for name in BODY_PREFERENCE if name != "pdf")
    assert BODY_PREFERENCE == ("xml", "uslm", "htm", "txt", "pdf")
    # Not ("pdf",): a package that offers no PDF still yields a body.
    assert len(PRINT_BODY_PREFERENCE) == len(BODY_PREFERENCE)


def test_the_print_preference_takes_the_pdf_of_a_package_that_offers_both() -> None:
    """The print preference takes the PDF of a package offering both, without requesting HTML."""
    transport = Transport(**{PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf")})
    result = acquire(transport, prefer=PRINT_BODY_PREFERENCE)

    assert result.offered_formats == ("htm", "pdf")
    assert result.format == "pdf"
    assert transport.urls[-1] == PDF_URL
    assert HTM_URL not in transport.urls


def test_the_print_preference_still_reaches_a_text_rendition_when_no_pdf_is_offered() -> None:
    """The print preference still reaches a text rendition when no PDF is offered."""
    htm_only = f'<url displayLabel="HTML rendition" access="raw object">{HTM_URL}</url>'
    transport = Transport(**{MODS_URL: reply(mods_xml(urls=htm_only), content_type="application/xml")})
    result = acquire(transport, prefer=PRINT_BODY_PREFERENCE)

    assert result.offered_formats == ("htm",)
    assert result.format == "htm"


def test_pdf_is_last_under_the_default_so_an_offered_text_rendition_wins() -> None:
    """PDF is last under the default, so an offered text rendition wins and PDF is never requested."""
    transport = Transport(**{PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf")})
    result = acquire(transport)

    assert BODY_PREFERENCE[-1] == "pdf"
    assert result.offered_formats == ("htm", "pdf")
    assert result.format == "htm"
    assert PDF_URL not in transport.urls


def test_a_pdf_only_package_yields_a_body_under_the_default() -> None:
    """A PDF-only package yields a body under the default, which the previous default refused."""
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
    """A PDF without its magic is refused with its bytes at the body stage."""
    transport = Transport(**{PDF_URL: reply(b"<html>not a pdf</html>", content_type="application/pdf")})
    with pytest.raises(GovInfoBodySourceError, match="%PDF-") as caught:
        acquire(transport, prefer=("pdf",))

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == b"<html>not a pdf</html>" and refusal.stage == "source-validation"
    assert caught.value.__dict__["govinfo_body_acquisition"]["stage"] == "body"


def test_a_format_the_package_does_not_offer_refuses_before_any_body_request() -> None:
    """A format the package does not offer refuses before any body request, with the stage and offered formats
    recorded.
    """
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
    """A preferred format stated elsewhere refuses as a moved rendition, not as absence."""
    # A folder this module does not derive for a supported file type -- xml
    # is chosen because it and uslm share the extension the folder-less
    # classifier reads (bodies._FORMAT_BY_EXTENSION's documented tie-break).
    moved = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/alt/{PACKAGE}.xml"
    renditions = f'<url displayLabel="XML rendition" access="raw object">{moved}</url>'
    transport = Transport(**{MODS_URL: reply(mods_xml(urls=renditions), content_type="application/xml")})
    with pytest.raises(GovInfoRenditionAddressError, match="not where this module fetches it") as caught:
        acquire(transport, prefer=("xml",))

    # The package does state XML; it states it somewhere this module does not
    # derive, which is a different answer from "no XML rendition exists".
    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.moved_renditions == (("xml", moved),)
    assert moved in str(caught.value)


def test_a_one_part_report_is_fetched_at_its_parts_stem_never_the_package_stem() -> None:
    """CRPT-119hrpt811 states only its part 1, so the body is proved and fetched at that part's stem.

    The package stem redirects to the error page for this package (fixture README), and the transport answers only
    the routes named here, so a request for it would fail the test.
    """
    api = f"https://api.govinfo.gov/packages/{PART_PACKAGE}"
    part_url = f"https://www.govinfo.gov/content/pkg/{PART_PACKAGE}/html/{PART}.htm"
    transport = Transport(
        **{
            f"{api}/summary": reply(PART_SUMMARY, content_type="application/json"),
            f"{api}/mods": reply(PART_MODS, content_type="application/xml"),
            part_url: HTML_BODY,
        }
    )
    result = acquire(transport, package_id=PART_PACKAGE)

    assert transport.urls == [f"{api}/summary", f"{api}/mods", part_url]
    assert result.identity.package_id == result.summary.identity.package_id == PART_PACKAGE
    assert result.mods.part_id == result.body.part_id == PART
    assert (result.format, result.offered_formats) == ("htm", ("pdf", "htm"))
    assert result.body.final_url == result.body_capture.resolved_url == part_url


MULTIPART = "CRPT-119hrpt455"
UNSUFFIXED = "CRPT-119hrpt494"
PART_2_BODY = reply((FIXTURES / f"body-{UNSUFFIXED}-pt2.htm").read_bytes(), content_type="text/html")


def multipart_transport(package: str, **bodies) -> Transport:
    """The package's real summary and MODS, and the named part bodies; nothing else answers."""
    api = f"https://api.govinfo.gov/packages/{package}"
    return Transport(
        **{
            f"{api}/summary": reply(
                (FIXTURES / f"summary-{package}.json").read_bytes(), content_type="application/json"
            ),
            f"{api}/mods": reply((FIXTURES / f"mods-{package}.xml").read_bytes(), content_type="application/xml"),
            **{f"https://www.govinfo.gov/content/pkg/{package}/html/{part}.htm": body for part, body in bodies.items()},
        }
    )


def acquire_parts(transport: Transport, package_id: str, **arguments) -> tuple[GovInfoPackageBody, ...]:
    """Acquire every part of one package through the transport."""
    budget = arguments.pop("budget", replace(BUDGET, max_requests=6))
    with GovInfoBodyAcquirer(budget=budget, api_key=KEY, transport=transport, clock=lambda: NOW) as client:
        return client.acquire_parts(package_id, **arguments)


def test_every_part_is_fetched_once_at_its_own_stem_under_one_summary_and_mods() -> None:
    """CRPT-119hrpt455 publishes two parts and nothing at its root: two bodies, each proved at its part's stem.

    The part bodies here are stand-ins (identity rests on the locator); the summary and MODS are the publisher's.
    """
    parts = (f"{MULTIPART}-pt1", f"{MULTIPART}-pt2")
    transport = multipart_transport(MULTIPART, **dict.fromkeys(parts, HTML_BODY))
    bodies = acquire_parts(transport, MULTIPART)

    assert len(transport.urls) == 4 and transport.urls[2:] == [body.body.final_url for body in bodies]
    assert [(body.part.part_id, body.part.part_number, body.body.part_id) for body in bodies] == [
        (parts[0], 1, parts[0]),
        (parts[1], 2, parts[1]),
    ]
    assert [body.body.final_url.rsplit("/", 1)[1] for body in bodies] == [f"{part}.htm" for part in parts]
    assert all(body.format == "htm" and body.offered_formats == ("pdf", "htm") for body in bodies)
    # One summary and one MODS prove both parts; each result carries them beside its own body.
    assert {body.summary_capture.sha256 for body in bodies} == {bodies[0].summary_capture.sha256}
    assert {body.request_count for body in bodies} == {4}
    assert [body.part.primary_bill.number for body in bodies] == ["5103", "5103"]


def test_an_unsuffixed_part_1_is_fetched_at_the_package_stem_beside_its_part_2() -> None:
    """CRPT-119hrpt494: Part 1 is the package stem, Part 2 its ``-pt2`` (the publisher's own 1,490 bytes)."""
    transport = multipart_transport(UNSUFFIXED, **{UNSUFFIXED: HTML_BODY, f"{UNSUFFIXED}-pt2": PART_2_BODY})
    first, second = acquire_parts(transport, UNSUFFIXED)

    assert (first.part.part_id, first.part.part_number) == (UNSUFFIXED, 1)
    assert first.body.final_url == f"https://www.govinfo.gov/content/pkg/{UNSUFFIXED}/html/{UNSUFFIXED}.htm"
    assert (second.part.part_id, second.part.part_number, second.body.byte_size) == (f"{UNSUFFIXED}-pt2", 2, 1_490)
    assert b"SUPPLEMENTAL REPORT" in second.body_capture.body


def test_acquire_reads_only_the_roots_part_and_says_which_one_it_is() -> None:
    """``acquire`` on CRPT-119hrpt494 still reads the root, which is Part 1, and no longer silently.

    The result names its part, and ``mods.parts`` lists the Part 2 the root does not offer.
    """
    transport = multipart_transport(UNSUFFIXED, **{UNSUFFIXED: HTML_BODY})
    result = acquire(transport, package_id=UNSUFFIXED)

    assert result.part.part_id == result.body.part_id == UNSUFFIXED
    assert [part.part_id for part in result.mods.parts] == [UNSUFFIXED, f"{UNSUFFIXED}-pt2"]


def test_a_report_in_one_part_is_one_body_whichever_way_it_is_read() -> None:
    """A single-part report is its own one part: ``acquire_parts`` returns what ``acquire`` does."""
    (whole,) = acquire_parts(Transport(), PACKAGE)
    single = acquire(Transport())

    assert whole.part == single.part and whole.part.part_id == whole.body.part_id == PACKAGE
    assert whole.part.part_number is None
    assert (whole.body, whole.body_capture.body) == (single.body, single.body_capture.body)


def test_a_part_offering_no_preferred_format_refuses_the_package_before_any_body() -> None:
    """Every part's format is chosen before a body is requested, so a partial set is never fetched."""
    transport = multipart_transport(MULTIPART)
    with pytest.raises(GovInfoFormatNotOfferedError, match=f"{MULTIPART}-pt1 offers") as caught:
        acquire_parts(transport, MULTIPART, prefer=("xml",))

    assert len(transport.urls) == 2
    assert caught.value.__dict__["govinfo_body_acquisition"]["partId"] == f"{MULTIPART}-pt1"


def test_one_unavailable_part_refuses_the_whole_package() -> None:
    """A part whose stem redirects refuses the package: half a report is never a result."""
    redirect = reply(b"", status=302, location="https://www.govinfo.gov/error")
    transport = multipart_transport(MULTIPART, **{f"{MULTIPART}-pt1": HTML_BODY, f"{MULTIPART}-pt2": redirect})
    with pytest.raises(GovInfoPackageUnavailableError) as caught:
        acquire_parts(transport, MULTIPART)

    context = caught.value.__dict__["govinfo_body_acquisition"]
    assert (context["stage"], context["partId"], context["requestCount"]) == ("body", f"{MULTIPART}-pt2", 4)


def test_every_part_spends_the_one_request_budget() -> None:
    """``2 + P`` requests: a budget of three reaches the first part and refuses the second."""
    transport = multipart_transport(MULTIPART, **{f"{MULTIPART}-pt1": HTML_BODY})
    with pytest.raises(GovInfoBodySourceError, match="request budget"):
        acquire_parts(transport, MULTIPART, budget=replace(BUDGET, max_requests=3))
    assert len(transport.urls) == 3


def test_a_collection_that_states_no_parts_is_refused_by_acquire_parts() -> None:
    """A hearing has no report parts, so ``acquire_parts`` refuses it after reading its record."""
    hearing = "CHRG-119hhrg64242"
    api = f"https://api.govinfo.gov/packages/{hearing}"
    summary = SUMMARY.replace(PACKAGE.encode(), hearing.encode()).replace(b'"CRPT"', b'"CHRG"')
    transport = Transport(
        **{
            f"{api}/summary": reply(summary, content_type="application/json"),
            f"{api}/mods": reply(mods_xml(access_id=hearing, collection="CHRG"), content_type="application/xml"),
        }
    )
    with pytest.raises(GovInfoBodySourceError, match="state no parts"):
        acquire_parts(transport, hearing)
    assert len(transport.urls) == 2


def test_a_missing_package_is_unavailable_not_absent() -> None:
    """A missing package is unavailable, not absent, with its response retained."""
    missing = reply(b'{"message":"The requested resource does not exist."}', status=404, content_type="text/plain")
    transport = Transport(**{SUMMARY_URL: missing})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 404") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL]
    assert caught.value.capture.status_code == 404
    assert caught.value.__dict__["refused_response"].response_bytes is not None


def test_a_redirected_rendition_is_unavailable_and_never_followed() -> None:
    """A redirected rendition is unavailable and never followed, so absence cannot become a body."""
    # Measured: an absent or unoffered rendition answers 302 to /error, which
    # itself answers 200. Following it would turn absence into a body.
    transport = Transport(**{HTM_URL: reply(b"", status=302, location="https://www.govinfo.gov/error")})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 302") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert caught.value.capture.resolved_url == HTM_URL


def test_the_error_page_served_as_a_body_is_refused_with_its_bytes() -> None:
    """The error page served as a body is refused with its bytes and request key."""
    page = b'<html><a href="https://www.govinfo.gov/error">Page Not Found</a></html>'
    transport = Transport(**{HTM_URL: reply(page, content_type="text/html")})
    with pytest.raises(GovInfoBodySourceError, match="error page") as caught:
        acquire(transport)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == page and refusal.request_key == HTM_URL


def test_a_body_in_another_format_is_refused() -> None:
    """A body in another format is refused."""
    transport = Transport(**{HTM_URL: reply(BODY, content_type="application/pdf")})
    with pytest.raises(GovInfoBodySourceError, match="Content-Type"):
        acquire(transport)


def test_a_mods_access_id_for_another_package_refuses_before_the_body() -> None:
    """A MODS access id for another package refuses before the body is requested."""
    transport = Transport(**{MODS_URL: reply(mods_xml(access_id="CRPT-119hrpt2"), content_type="application/xml")})
    with pytest.raises(GovInfoBodySourceError, match="accessId differs") as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.__dict__["refused_response"].request_key == MODS_URL


def test_a_summary_for_another_package_refuses_before_the_mods() -> None:
    """A summary for another package refuses before the MODS is requested."""
    other = SUMMARY.replace(b'"packageId": "CRPT-119hrpt1"', b'"packageId": "CRPT-119hrpt2"')
    transport = Transport(**{SUMMARY_URL: reply(other, content_type="application/json")})
    with pytest.raises(GovInfoBodySourceError, match="packageId differs"):
        acquire(transport)


@pytest.mark.parametrize("status", [401, 403])
def test_a_keyed_credential_refusal_aborts_without_retaining_bytes(status: int) -> None:
    """A keyed credential refusal aborts without retaining bytes or a capture."""
    transport = Transport(**{SUMMARY_URL: reply(b"credential material", status=status)})
    with pytest.raises(CredentialRefusedError) as caught:
        acquire(transport)

    assert transport.urls == [SUMMARY_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert isinstance(refusal, RefusedResponse) and refusal.response_bytes is None
    assert "capture" not in caught.value.__dict__


def test_a_keyless_wall_keeps_the_publishers_own_answer() -> None:
    """A keyless wall keeps the publisher's own answer while keyed routes retain none."""
    wall = b"<html>Access denied by the edge</html>"
    transport = Transport(**{HTM_URL: reply(wall, status=403, content_type="text/html")})
    with pytest.raises(CredentialRefusedError) as caught:
        acquire(transport)

    # The body routes carry no credential, so a 403 there is the publisher's
    # answer and is worth keeping; the keyed routes never retain one.
    assert caught.value.__dict__["refused_response"].response_bytes == wall


def test_a_keyed_response_that_echoes_the_credential_is_refused_unretained() -> None:
    """A keyed response echoing the credential is refused without retaining it."""
    transport = Transport(**{MODS_URL: reply(KEY.encode(), content_type="application/xml")})
    with pytest.raises(CredentialRefusedError, match="echoed"):
        acquire(transport)


def test_both_clients_spend_one_request_budget() -> None:
    """Both clients spend one request budget, with the body refusal attributed to the next request."""
    transport = Transport()
    with pytest.raises(GovInfoBodySourceError, match="request budget") as caught:
        acquire(transport, budget=replace(BUDGET, max_requests=2))

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == HTM_URL and refusal.stage == "before-request"
    assert refusal.unavailable_reason == "request-budget-exhausted"


def test_a_retry_spends_the_same_budget_as_the_metadata_requests() -> None:
    """A retry spends the same budget as the metadata requests."""
    attempts = iter([reply(b"", status=503), HTML_BODY])
    transport = Transport(**{HTM_URL: lambda: next(attempts)()})
    result = acquire(transport, budget=replace(BUDGET, max_requests=4))

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL, HTM_URL]
    assert result.request_count == 4


def test_a_body_over_its_bound_returns_no_partial_bytes() -> None:
    """A body over its bound returns no partial bytes and records the lowered bound."""
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
        ({"prefer": ("jpeg",)}, ValueError),
        ({"prefer": "htm"}, TypeError),
        ({"max_bytes": 0}, ValueError),
    ],
)
def test_invalid_selections_refuse_before_any_request(arguments: dict, error: type[Exception]) -> None:
    """Invalid selections refuse before any request."""
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
    """Invalid budget values are refused naming the field."""
    with pytest.raises(ValueError, match=field):
        replace(BUDGET, **{field: value})


def test_an_acquirer_without_a_credential_refuses_to_exist() -> None:
    """An acquirer without a credential refuses to be constructed."""
    with pytest.raises(ValueError, match="api_key"):
        GovInfoBodyAcquirer(budget=BUDGET, api_key="", transport=Transport())


def test_a_closed_client_refuses_without_a_request() -> None:
    """A closed client refuses without making a request."""
    transport = Transport()
    client = GovInfoBodyAcquirer(budget=BUDGET, api_key=KEY, transport=transport)
    client.close()
    with pytest.raises(ValueError, match="closed"):
        client.acquire(PACKAGE)
    assert not transport.calls


LIVE_BUDGET = GovInfoBodyBudget(
    max_requests=6,
    max_body_bytes=24 * 1024 * 1024,
    max_metadata_bytes=8 * 1024 * 1024,
    timeout_seconds=60.0,
    min_request_interval_seconds=0.5,
)


@pytest.mark.integration
@pytest.mark.parametrize("package_id", ["CRPT-119hrpt1", "CHRG-119hhrg64242"])
def test_live_package_body_is_acquired_and_proved(package_id: str) -> None:
    """Live: the package body is acquired and proved for both collections, without an error page or key."""
    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    key = read_api_key(ENV_FILE, "API_GOV")
    with GovInfoBodyAcquirer(budget=LIVE_BUDGET, api_key=key) as client:
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


@pytest.mark.integration
def test_live_parts_are_each_acquired_at_their_own_stem() -> None:
    """Live: CRPT-119hrpt455's two parts are each proved at their own stem, as on 2026-09-23 (fixture README)."""
    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    key = read_api_key(ENV_FILE, "API_GOV")
    with GovInfoBodyAcquirer(budget=LIVE_BUDGET, api_key=key) as client:
        bodies = client.acquire_parts(MULTIPART)

    assert [body.part.part_id for body in bodies] == [f"{MULTIPART}-pt1", f"{MULTIPART}-pt2"]
    for body in bodies:
        assert body.body.final_url.endswith(f"/{body.part.part_id}.{body.format}")
        assert body.body_capture.status_code == 200 and body.body_capture.byte_size > 1_000
        assert key.encode() not in body.body_capture.body
