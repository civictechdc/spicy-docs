"""Acquire one GovInfo granule body over real HTTPX streams, offline (B2).

The three CREC-2026-09-18-pt1-PgS4837-4 fixtures are exact publisher
responses; every refusal case is synthetic except the wrong-package one,
which inlines the real 400 body measured live (fixture README). The live
case is marked ``integration`` and skipped without a credential file.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.govinfo.bodies import GRANULE_BODY_PREFERENCE, GovInfoBodySourceError
from spicy_docs.sources.govinfo.body_acquisition import (
    GovInfoBodyAcquirer,
    GovInfoBodyBudget,
    GovInfoFormatNotOfferedError,
    GovInfoGranuleBody,
    GovInfoPackageUnavailableError,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import read_api_key

from .test_govinfo_granule_bodies import BODY, MODS, SUMMARY, granule_mods_xml

PACKAGE = "CREC-2026-09-18"
GRANULE = "CREC-2026-09-18-pt1-PgS4837-4"
SUMMARY_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{GRANULE}/summary"
MODS_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{GRANULE}/mods"
HTM_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{GRANULE}.htm"
PDF_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{GRANULE}.pdf"
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


def reply(body: bytes, *, status: int = 200, content_type: str | None = None):
    """An HTTPX response over the given body."""
    headers = {}
    if content_type is not None:
        headers["content-type"] = content_type
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


def acquire_granule(transport: Transport, **arguments) -> GovInfoGranuleBody:
    """Acquire the fixture granule through the transport."""
    budget = arguments.pop("budget", BUDGET)
    with GovInfoBodyAcquirer(budget=budget, api_key=KEY, transport=transport, clock=lambda: NOW) as client:
        package_id = arguments.pop("package_id", PACKAGE)
        granule_id = arguments.pop("granule_id", GRANULE)
        return client.acquire_granule(package_id, granule_id, **arguments)


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_acquires_the_first_offered_preferred_format_with_every_capture() -> None:
    """Acquisition takes the first offered preferred format, keeping every capture and the real MODS document order."""
    transport = Transport()
    result = acquire_granule(transport)

    assert transport.urls == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert result.request_count == 3
    assert result.format == "htm"
    assert result.preference == GRANULE_BODY_PREFERENCE == ("htm", "pdf")
    # The real MODS states PDF before HTML in document order; the preference
    # order picks HTML anyway.
    assert result.offered_formats == ("pdf", "htm")
    assert result.identity.package.package_id == PACKAGE
    assert result.identity.granule_id == GRANULE
    assert result.mods.host_package_ids == (PACKAGE,)
    assert result.body.byte_size == len(BODY)
    assert result.body_capture.body == BODY
    assert [capture.status_code for capture in result.captures] == [200, 200, 200]
    assert [capture.resolved_url for capture in result.captures] == [SUMMARY_URL, MODS_URL, HTM_URL]
    assert result.body_capture.content_type == "text/html"
    assert result.budget == BUDGET


def test_the_credential_travels_only_to_the_keyed_routes() -> None:
    """The credential travels only to the keyed routes."""
    transport = Transport()
    acquire_granule(transport)

    keyed, keyless = transport.calls[:2], transport.calls[2]
    assert all(call.headers["x-api-key"] == KEY for call in keyed)
    assert "x-api-key" not in keyless.headers


def test_pdf_is_reached_when_the_granule_does_not_offer_htm() -> None:
    """PDF is reached when the granule offers no HTML."""
    pdf_only = f'<url displayLabel="PDF rendition" access="raw object">{PDF_URL}</url>'
    body = granule_mods_xml(urls=pdf_only)
    transport = Transport(
        **{
            MODS_URL: reply(body, content_type="application/xml"),
            PDF_URL: reply(b"%PDF-1.4\nbody", content_type="application/pdf"),
        }
    )
    result = acquire_granule(transport)

    assert result.offered_formats == ("pdf",)
    assert result.format == "pdf"


def test_a_wrong_day_granule_id_under_the_right_package_is_unavailable() -> None:
    """A wrong-day granule id under the right package is unavailable, since GovInfo answers 400 for it."""
    # Measured live 2026-09-19: GovInfo answers 400, not 404, for a granule
    # that does not belong to the requested package; the body carries
    # neither packageId nor granuleId, so it is typed the same way a
    # package's own 404/410 is.
    other_gid = "CREC-2026-09-17-pt1-PgS4800"
    other_url = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{other_gid}/summary"
    transport = Transport(**{other_url: reply(b'{"message":"invalid granuleId"}', status=400)})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 400") as caught:
        acquire_granule(transport, granule_id=other_gid)

    assert transport.urls == [other_url]
    assert caught.value.capture.status_code == 400


def test_the_same_real_granule_requested_under_the_wrong_package_is_unavailable() -> None:
    """The same real granule under the wrong package is unavailable."""
    # The other direction of the same measurement: this fixture's own real
    # granule id, requested under a different real day.
    other_package = "CREC-2026-09-17"
    other_url = f"https://api.govinfo.gov/packages/{other_package}/granules/{GRANULE}/summary"
    transport = Transport(**{other_url: reply(b'{"message":"invalid granuleId"}', status=400)})
    with pytest.raises(GovInfoPackageUnavailableError, match="HTTP 400"):
        acquire_granule(transport, package_id=other_package)

    assert transport.urls == [other_url]


def test_a_400_with_a_different_body_is_not_relabeled_unavailable() -> None:
    """A 400 with a different body is not relabeled unavailable and keeps its refused bytes."""
    # Only the documented {"message":"invalid granuleId"} shape is retyped;
    # any other 400 falls through as the generic source error, with its
    # capture, rather than being guessed at.
    other_gid = "CREC-2026-09-17-pt1-PgS4800"
    other_url = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{other_gid}/summary"
    transport = Transport(**{other_url: reply(b'{"message":"rate limited"}', status=400)})
    with pytest.raises(GovInfoBodySourceError, match="HTTP 400") as caught:
        acquire_granule(transport, granule_id=other_gid)

    assert not isinstance(caught.value, GovInfoPackageUnavailableError)
    assert transport.urls == [other_url]
    refused = caught.value.__dict__["refused_response"]
    assert refused.response_bytes == b'{"message":"rate limited"}'


def test_a_400_with_an_unparseable_body_is_not_relabeled_unavailable() -> None:
    """A 400 with an unparseable body is not relabeled unavailable."""
    other_gid = "CREC-2026-09-17-pt1-PgS4800"
    other_url = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{other_gid}/summary"
    transport = Transport(**{other_url: reply(b"not json", status=400)})
    with pytest.raises(GovInfoBodySourceError, match="HTTP 400") as caught:
        acquire_granule(transport, granule_id=other_gid)

    assert not isinstance(caught.value, GovInfoPackageUnavailableError)


def test_a_format_the_granule_does_not_offer_refuses_before_any_body_request() -> None:
    """A format the granule does not offer refuses before any body request, with the stage and offered formats
    recorded.
    """
    transport = Transport()
    with pytest.raises(GovInfoFormatNotOfferedError, match="none matches") as caught:
        acquire_granule(transport, prefer=("xml",))

    assert transport.urls == [SUMMARY_URL, MODS_URL]
    assert caught.value.offered_formats == ("pdf", "htm")
    context = caught.value.__dict__["govinfo_granule_acquisition"]
    assert context["packageId"] == PACKAGE and context["granuleId"] == GRANULE
    assert context["stage"] == "mods" and context["format"] is None


def test_a_missing_summary_field_refuses_at_the_summary_stage() -> None:
    """A missing summary field refuses at the summary stage."""
    bad = reply(b'{"packageId": "' + PACKAGE.encode() + b'"}', content_type="application/json")
    transport = Transport(**{SUMMARY_URL: bad})
    with pytest.raises(GovInfoBodySourceError, match="granuleId"):
        acquire_granule(transport)

    assert transport.urls == [SUMMARY_URL]


@pytest.mark.integration
def test_live_granule_body_is_acquired_and_proved() -> None:
    """Live: the granule body is acquired and proved without an error page or key."""
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
        result = client.acquire_granule(PACKAGE, GRANULE)

    assert result.identity.package.package_id == PACKAGE
    assert result.identity.granule_id == GRANULE
    assert result.format == "htm"
    assert result.body_capture.status_code == 200
    assert result.body_capture.byte_size > 100
    assert b"govinfo.gov/error" not in result.body_capture.body
    assert key.encode() not in result.body_capture.body
