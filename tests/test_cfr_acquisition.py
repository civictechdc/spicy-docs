"""CFR source requests preserve exact responses, bounds and refusal evidence."""

import gzip
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.cfr.acquisition import CfrAcquirer, CfrAcquisitionBudget, CfrSourceUnavailableError
from spicy_docs.sources.cfr.models import AnnualCfrSelection, CfrSourceError, EcfrSelection
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

# Constructed source-shaped input; native revision deliberately differs from the
# requested date, since API selection and printed amendment dates are distinct.
BODY = b"""<ECFR><AMDDATE>Dec. 29, 2022</AMDDATE><DIV1 TYPE="TITLE" N="1"><HEAD>Title 1</HEAD>
<DIV5 TYPE="PART" N="1">
<DIV8 TYPE="SECTION" N="1.1"><HEAD>Section 1.1</HEAD><P>Original text.</P>
</DIV8></DIV5></DIV1></ECFR>"""
SELECTION = EcfrSelection(1, "2026-08-10")
BUDGET = CfrAcquisitionBudget(3, 4096, 7, 0)
NOW = datetime(2026, 9, 12, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "cfr"


def response(body=BODY, status=200, *, content_type="application/xml", **headers):
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


def test_exact_capture_request_date_and_native_metadata_remain_distinct():
    transport = Transport(response())
    with CfrAcquirer(budget=BUDGET, transport=transport, clock=lambda: NOW) as source:
        result = source.acquire_ecfr(SELECTION)
    assert result.capture.body == BODY
    assert result.selection == SELECTION
    assert result.identity.title == 1
    assert result.identity.amendment_dates == ("Dec. 29, 2022",)
    assert result.capture.requested_url == "https://www.ecfr.gov/api/versioner/v1/full/2026-08-10/title-1.xml"
    assert result.capture.resolved_url == result.capture.requested_url
    assert result.capture.observed_at == "2026-09-12T00:00:00Z"
    assert result.capture.byte_size == len(BODY)
    assert result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].method == "GET"
    assert transport.calls[0].headers["accept-encoding"] == "gzip"
    assert result.xml is result.capture.body


@pytest.mark.parametrize(
    "operation,selection,fixture,expected_url",
    [
        ("ecfr_titles", None, "ecfr-titles.json", "https://www.ecfr.gov/api/versioner/v1/titles.json"),
        (
            "ecfr",
            EcfrSelection(1, "2026-07-31", part="18"),
            "ecfr-api-part18.xml",
            "https://www.ecfr.gov/api/versioner/v1/full/2026-07-31/title-1.xml?part=18",
        ),
        (
            "ecfr",
            EcfrSelection(1, "2026-07-31", part="18", section="18.1"),
            "ecfr-api-section18-1.xml",
            "https://www.ecfr.gov/api/versioner/v1/full/2026-07-31/title-1.xml?part=18&section=18.1",
        ),
        (
            "annual",
            AnnualCfrSelection(2025, 1, 1),
            "annual-title1-vol1.xml",
            "https://www.govinfo.gov/bulkdata/CFR/2025/title-1/CFR-2025-title1-vol1.xml",
        ),
        (
            "annual",
            AnnualCfrSelection(2025, 30, 3, section="716.2"),
            "annual-title30-vol3-sec716-2.xml",
            "https://www.govinfo.gov/content/pkg/CFR-2025-title30-vol3/xml/CFR-2025-title30-vol3-sec716-2.xml",
        ),
        ("ecfr_bulk", 1, "ecfr-bulk-title1.xml", "https://www.govinfo.gov/bulkdata/ECFR/title-1/ECFR-title1.xml"),
    ],
)
def test_explicit_routes_capture_original_publisher_fixture_bytes(operation, selection, fixture, expected_url):
    body = (FIXTURES / fixture).read_bytes()
    media_type = "application/json" if fixture.endswith(".json") else "text/xml; charset=UTF-8"
    transport = Transport(response(body, content_type=media_type))
    with CfrAcquirer(budget=replace(BUDGET, max_bytes=65536), transport=transport) as source:
        method = getattr(source, "acquire_" + operation)
        result = method() if selection is None else method(selection)
    assert result.capture.body == body
    assert result.capture.requested_url == expected_url
    assert result.request_count == 1
    if operation == "ecfr_titles":
        assert len(result.titles.titles) == 50
    else:
        assert result.selection == selection


@pytest.mark.parametrize("status", [404, 410])
def test_exact_unavailable_response_is_retained_without_another_route(status):
    transport = Transport(response(b"unavailable here", status))
    with (
        CfrAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CfrSourceUnavailableError) as raised,
    ):
        source.acquire_ecfr(SELECTION)
    assert raised.value.capture.body == b"unavailable here"
    assert raised.value.refused_response.response_bytes == b"unavailable here"
    assert raised.value.cfr_acquisition["requestCount"] == len(transport.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_aborts_without_reading_or_retaining_body(status):
    class ForbiddenBody(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("must not read credential refusal body")

    transport = Transport(httpx.Response(status, stream=ForbiddenBody()))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.acquire_ecfr(SELECTION)
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.cfr_acquisition["requestCount"] == len(transport.calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        response(b"<html>Challenge page</html>", content_type="text/html"),
        response(b"<html>Challenge page</html>"),
        response(BODY.replace(b'N="1"', b'N="2"', 1)),
        response(b""),
        response(BODY[:-5]),
        response(status=302, location="https://example.invalid/other.xml"),
        response(**{"content-length": str(len(BODY) + 1)}),
    ],
)
def test_wrong_shape_identity_redirect_or_incomplete_response_never_succeeds(answer):
    transport = Transport(answer)
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CfrSourceError) as raised:
        source.acquire_ecfr(SELECTION)
    assert len(transport.calls) == 1
    assert raised.value.refused_response.response_bytes is not None


def test_retries_consume_request_budget_and_next_operation_starts_a_new_count():
    transport = Transport(response(status=503), response(), response())
    with CfrAcquirer(budget=BUDGET, transport=transport) as source:
        first = source.acquire_ecfr(SELECTION)
        second = source.acquire_ecfr(SELECTION)
    assert (first.request_count, second.request_count) == (2, 1)
    assert len(transport.calls) == 3


def test_exhausted_transient_response_does_not_establish_source_absence():
    transport = Transport(response(status=503), response(status=503))
    with (
        CfrAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as source,
        pytest.raises(RetryableHTTPStatusError) as raised,
    ):
        source.acquire_ecfr(SELECTION)
    assert len(transport.calls) == raised.value.cfr_acquisition["requestCount"] == 2
    assert raised.value.refused_response.response_bytes is None


def test_effective_byte_allowance_is_recorded_and_cannot_raise_the_client_limit():
    transport = Transport(response(), response())
    with CfrAcquirer(budget=BUDGET, transport=transport) as source:
        small = source.acquire_ecfr(SELECTION, max_bytes=len(BODY))
        large = source.acquire_ecfr(SELECTION, max_bytes=BUDGET.max_bytes * 2)
    assert small.budget.max_bytes == len(BODY)
    assert large.budget == BUDGET


@pytest.mark.parametrize("with_length", [False, True])
def test_byte_overrun_has_no_successful_partial_capture(with_length):
    headers = {"content-length": str(len(BODY))} if with_length else {}
    transport = Transport(response(**headers))
    with (
        CfrAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CfrSourceError, match="byte bound") as raised,
    ):
        source.acquire_ecfr(SELECTION, max_bytes=len(BODY) - 1)
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.cfr_acquisition["budget"]["max_bytes"] == len(BODY) - 1


def test_configuration_cannot_diverge_and_closed_client_cannot_make_requests():
    transport = Transport()
    source = CfrAcquirer(budget=BUDGET, transport=transport)
    with pytest.raises(AttributeError):
        source.budget = replace(BUDGET, max_requests=20)
    source.close()
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.acquire_ecfr(SELECTION)
    assert not transport.calls


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_byte_allowance_never_makes_a_request(limit):
    transport = Transport()
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ValueError):
        source.acquire_ecfr(SELECTION, max_bytes=limit)
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


def test_gzip_preserves_exact_payload_and_independently_validates_decoded_xml():
    wire = gzip.compress(BODY, mtime=0)
    transport = Transport(response(wire, **{"content-encoding": "gzip", "content-length": str(len(wire))}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_ecfr(SELECTION)
    assert result.capture.body == wire
    assert result.capture.content_encoding == "gzip"
    assert result.capture.byte_size == len(wire)
    assert result.xml == BODY and result.identity.title == 1


@pytest.mark.parametrize(
    "wire",
    [
        b"not gzip",
        gzip.compress(BODY)[:-5],
        gzip.compress(BODY) + b"trailing",
        gzip.compress(BODY) + gzip.compress(BODY),
        gzip.compress(b"x" * (BUDGET.max_bytes + 1)),
        gzip.compress(BODY.replace(b'N="1"', b'N="2"', 1)),
    ],
)
def test_gzip_refusal_retains_wire_payload_and_encoding(wire):
    transport = Transport(response(wire, **{"content-encoding": "gzip"}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CfrSourceError) as raised:
        source.acquire_ecfr(SELECTION)
    assert raised.value.capture.body == wire
    assert raised.value.capture.content_encoding == "gzip"
    assert raised.value.refused_response.response_bytes == wire
    assert len(transport.calls) == 1


def test_gzip_checks_content_length_against_wire_and_bounds_decoded_bytes_separately():
    wire = gzip.compress(BODY)
    transport = Transport(response(wire, **{"content-encoding": "gzip", "content-length": str(len(wire) + 1)}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CfrSourceError) as raised:
        source.acquire_ecfr(SELECTION)
    assert "Content-Length" in str(raised.value)
    assert raised.value.capture.body == wire
    assert raised.value.capture.content_encoding == "gzip"
    transport = Transport(response(wire, **{"content-encoding": "gzip"}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CfrSourceError, match="decoded XML"):
        source.acquire_ecfr(SELECTION, max_bytes=len(BODY) - 1)


def test_gzip_accepts_exact_decoded_byte_bound():
    wire = gzip.compress(BODY)
    transport = Transport(response(wire, **{"content-encoding": "gzip"}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_ecfr(SELECTION, max_bytes=len(BODY))
    assert result.xml == BODY


def test_annual_source_keeps_identity_encoding_and_refuses_unsolicited_compression():
    transport = Transport(response(gzip.compress(BODY), **{"content-encoding": "gzip"}))
    with CfrAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CfrSourceError, match="encoding"):
        source.acquire_annual(AnnualCfrSelection(2025, 1, 1))
    assert transport.calls[0].headers["accept-encoding"] == "identity"
