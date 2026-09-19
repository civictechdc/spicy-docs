"""USLM source requests preserve exact responses, bounds and refusal evidence."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.govinfo.uslm import PublicLawSelection, StatuteCompilationSelection, UslmSourceError
from spicy_docs.sources.govinfo.uslm_acquisition import (
    UslmAcquirer,
    UslmAcquisitionBudget,
    UslmSourceUnavailableError,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError
from tests.source_fixtures import archive_bytes as archive

FIXTURES = Path(__file__).parent / "fixtures" / "uslm"
LAW_XML = (FIXTURES / "plaw-119publ1.xml").read_bytes()
COMPS_XML = (FIXTURES / "comps-10542.xml").read_bytes()
LAW = PublicLawSelection(119, "public", 1)
COMPILATION = StatuteCompilationSelection(10542)
BUDGET = UslmAcquisitionBudget(3, 65536, 7, 0)
NOW = datetime(2026, 9, 14, tzinfo=UTC)


LAW_ZIP = archive(("PLAW-119publ1.xml", LAW_XML))
COMPS_ZIP = archive(("COMPS-10542.xml", COMPS_XML))


def response(body=LAW_XML, status=200, *, content_type="application/xml", **headers):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type, **headers})


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


def test_exact_capture_and_native_metadata_for_one_law():
    transport = Transport(response())
    with UslmAcquirer(budget=BUDGET, transport=transport, clock=lambda: NOW) as source:
        result = source.acquire_public_law(LAW)
    assert result.capture.body == LAW_XML
    assert result.selection == LAW
    assert result.metadata.citable_as == ("Public Law 119–1", "139 Stat. 3")
    assert result.capture.requested_url == "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119publ1.xml"
    assert result.capture.resolved_url == result.capture.requested_url
    assert result.capture.observed_at == "2026-09-14T00:00:00Z"
    assert result.capture.byte_size == len(LAW_XML)
    assert result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].method == "GET"
    assert transport.calls[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "operation,args,body,media_type,expected_url",
    [
        (
            "public_law",
            (LAW,),
            LAW_XML,
            "text/xml; charset=UTF-8",
            "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119publ1.xml",
        ),
        (
            "statute_compilation",
            (COMPILATION,),
            COMPS_XML,
            "text/xml",
            "https://www.govinfo.gov/bulkdata/COMPS/COMPS-10542.xml",
        ),
        (
            "public_law_archive",
            (119, "public"),
            LAW_ZIP,
            "application/zip",
            "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119-public.zip",
        ),
        (
            "statute_compilations_archive",
            (),
            COMPS_ZIP,
            "application/zip",
            "https://www.govinfo.gov/bulkdata/COMPS/COMPS.zip",
        ),
    ],
)
def test_every_route_captures_original_bytes(operation, args, body, media_type, expected_url):
    transport = Transport(response(body, content_type=media_type))
    with UslmAcquirer(budget=BUDGET, transport=transport) as source:
        result = getattr(source, "acquire_" + operation)(*args)
    assert result.capture.body == body
    assert result.capture.requested_url == expected_url
    assert result.request_count == 1
    if operation.endswith("archive"):
        assert len(result.archive.entries) == 1
        assert result.selection == ((119, "public") if args else None)
    else:
        assert result.selection == args[0]


@pytest.mark.parametrize("status", [404, 410])
def test_exact_unavailable_response_is_retained_without_another_route(status):
    transport = Transport(response(b"unavailable here", status))
    with (
        UslmAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UslmSourceUnavailableError) as raised,
    ):
        source.acquire_public_law_archive(113, "private")
    assert raised.value.capture.body == b"unavailable here"
    assert raised.value.refused_response.response_bytes == b"unavailable here"
    assert raised.value.uslm_acquisition == {
        "operation": "public-law-archive",
        "selection": {"congress": 113, "kind": "private"},
        "requestCount": 1,
        "budget": {"max_requests": 3, "max_bytes": 65536, "timeout_seconds": 7, "min_request_interval_seconds": 0},
    }
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_aborts_without_reading_or_retaining_body(status):
    class ForbiddenBody(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("must not read credential refusal body")

    transport = Transport(httpx.Response(status, stream=ForbiddenBody()))
    with UslmAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.acquire_statute_compilation(COMPILATION)
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.uslm_acquisition["requestCount"] == len(transport.calls) == 1
    assert raised.value.uslm_acquisition["selection"] == {"file_id": 10542}


@pytest.mark.parametrize(
    "answer",
    [
        response(b"<html>Govinfo Bulkdata Service Error</html>", content_type="text/html"),
        response(b"<html>Govinfo Bulkdata Service Error</html>"),
        response(LAW_XML.replace(b"<congress>119</congress>", b"<congress>118</congress>", 1)),
        response(b""),
        response(LAW_XML[:-5]),
        response(status=302, location="https://example.invalid/other.xml"),
        response(**{"content-length": str(len(LAW_XML) + 1)}),
        response(LAW_ZIP, content_type="application/zip"),
    ],
)
def test_wrong_shape_identity_redirect_or_incomplete_response_never_succeeds(answer):
    transport = Transport(answer)
    with UslmAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UslmSourceError) as raised:
        source.acquire_public_law(LAW)
    assert len(transport.calls) == 1
    assert raised.value.refused_response.response_bytes is not None


@pytest.mark.parametrize(
    "answer",
    [
        response(LAW_XML, content_type="application/zip"),
        response(LAW_ZIP),
        response(archive(("PLAW-118publ1.xml", LAW_XML)), content_type="application/zip"),
        response(b"PK\x03\x04junk", content_type="application/zip"),
    ],
)
def test_archive_route_refuses_wrong_media_type_or_foreign_entries(answer):
    transport = Transport(answer)
    with UslmAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UslmSourceError) as raised:
        source.acquire_public_law_archive(119, "public")
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.uslm_acquisition["operation"] == "public-law-archive"


def test_retries_consume_request_budget_and_next_operation_starts_a_new_count():
    transport = Transport(response(status=503), response(), response())
    with UslmAcquirer(budget=BUDGET, transport=transport) as source:
        first = source.acquire_public_law(LAW)
        second = source.acquire_public_law(LAW)
    assert (first.request_count, second.request_count) == (2, 1)
    assert len(transport.calls) == 3


def test_exhausted_transient_response_does_not_establish_source_absence():
    transport = Transport(response(status=503), response(status=503))
    with (
        UslmAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as source,
        pytest.raises(RetryableHTTPStatusError) as raised,
    ):
        source.acquire_public_law(LAW)
    assert len(transport.calls) == raised.value.uslm_acquisition["requestCount"] == 2
    assert raised.value.refused_response.response_bytes is None


def test_effective_byte_allowance_is_recorded_and_cannot_raise_the_client_limit():
    transport = Transport(response(), response())
    with UslmAcquirer(budget=BUDGET, transport=transport) as source:
        small = source.acquire_public_law(LAW, max_bytes=len(LAW_XML))
        large = source.acquire_public_law(LAW, max_bytes=BUDGET.max_bytes * 2)
    assert small.budget.max_bytes == len(LAW_XML)
    assert large.budget == BUDGET


@pytest.mark.parametrize("with_length", [False, True])
def test_byte_overrun_has_no_successful_partial_capture(with_length):
    headers = {"content-length": str(len(LAW_XML))} if with_length else {}
    transport = Transport(response(**headers))
    with (
        UslmAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UslmSourceError, match="byte bound") as raised,
    ):
        source.acquire_public_law(LAW, max_bytes=len(LAW_XML) - 1)
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.uslm_acquisition["budget"]["max_bytes"] == len(LAW_XML) - 1


def test_archive_entry_bounds_are_passed_through():
    transport = Transport(
        response(LAW_ZIP, content_type="application/zip"), response(LAW_ZIP, content_type="application/zip")
    )
    with UslmAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(UslmSourceError, match="max_entry_bytes"):
            source.acquire_public_law_archive(119, "public", max_entry_bytes=len(LAW_XML) - 1)
        with pytest.raises(UslmSourceError, match="max_entries"):
            source.acquire_statute_compilations_archive(max_entries=0)


def test_configuration_cannot_diverge_and_closed_client_cannot_make_requests():
    transport = Transport()
    source = UslmAcquirer(budget=BUDGET, transport=transport)
    with pytest.raises(AttributeError):
        source.budget = replace(BUDGET, max_requests=20)
    source.close()
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.acquire_public_law(LAW)
    assert not transport.calls
    with pytest.raises(TypeError):
        UslmAcquirer(budget=(3, 65536, 7, 0), transport=transport)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_byte_allowance_never_makes_a_request(limit):
    transport = Transport()
    with UslmAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ValueError):
        source.acquire_public_law(LAW, max_bytes=limit)
    assert not transport.calls


@pytest.mark.parametrize(
    "fields",
    [
        {"max_requests": True},
        {"max_requests": 0},
        {"max_bytes": 256 * 1024**2 + 1},
        {"max_bytes": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
        {"min_request_interval_seconds": float("inf")},
    ],
)
def test_invalid_budget_refuses(fields):
    with pytest.raises(ValueError):
        replace(BUDGET, **fields)


def test_unsolicited_compression_is_refused_and_identity_encoding_is_requested():
    transport = Transport(response(LAW_XML, **{"content-encoding": "gzip"}))
    with UslmAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UslmSourceError, match="encoding"):
        source.acquire_public_law(LAW)
    assert transport.calls[0].headers["accept-encoding"] == "identity"
