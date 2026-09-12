"""Exercise bounded, source-only GovInfo capture with real HTTPX streams."""

from __future__ import annotations

import hashlib
import traceback
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.congress import crs_summaries
from spicy_docs.sources.federal_register import body_acquisition as acquisition
from spicy_docs.sources.federal_register.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.sources.federal_register.body_sources import FederalRegisterBodySourceError
from spicy_docs.sources.refusals import RefusedResponse
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

BODY = b"<pre>Federal Register\n[FR Doc No: 98-14931]\nSynthetic body.</pre>"
MODS = b"""<mods xmlns="http://www.loc.gov/mods/v3">
<extension><accessId>FR-1998-06-03</accessId></extension>
<relatedItem type="constituent"><part><extent unit="pages"><start>30359</start></extent></part>
<extension><accessId>98-14931</accessId></extension></relatedItem></mods>"""
GRANULE_URL = "https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"
MODS_URL = "https://www.govinfo.gov/metadata/pkg/FR-1998-06-03/mods.xml"
BUDGET = GovInfoBodyBudget(3, 1024, 4096, 7.0, 0)
NOW = datetime(2026, 9, 11, tzinfo=UTC)


class Stream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.closed = False
        self.reads = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class Transport(httpx.MockTransport):
    def __init__(self, *actions: httpx.Response | Exception) -> None:
        self.actions = iter(actions)
        self.calls: list[httpx.Request] = []
        self.closed = False
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return action

    def close(self) -> None:
        self.closed = True


def response(body: bytes = BODY, status: int = 200, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, stream=Stream(body), headers={"content-type": "text/html", **(headers or {})})


def acquire(client: GovInfoBodyAcquirer) -> acquisition.GovInfoBodyAcquisition:
    return client.acquire(document_number="98-14931", publication_date="1998-06-03", route="granule")


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_direct_capture_is_exact_and_reusable_without_refetch(tmp_path) -> None:
    received = response(headers={"content-length": str(len(BODY))})
    transport = Transport(received)
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport, clock=lambda: NOW) as client:
        result = acquire(client)
        store = LocalSourceNativeBlobStore(tmp_path / "blobs")
        write = store.put_blob(result.body.sha256, result.body.byte_size, [result.body.body])
        with store.open(write.blob_ref) as retained:
            assert retained.read() == BODY
        assert not transport.closed

    assert len(transport.calls) == result.request_count == 1
    assert result.identity.source_document_number == result.identity.access_id == "98-14931"
    assert result.identity.match_kind == "exact-source"
    assert result.mods is result.mods_resolution is None
    assert result.body.body == BODY
    assert result.body.sha256 == "sha256:" + hashlib.sha256(BODY).hexdigest()
    assert result.body.observed_at == "2026-09-11T00:00:00Z"
    assert result.body.requested_url == result.body.resolved_url == GRANULE_URL
    assert result.budget == BUDGET
    assert transport.calls[0].extensions["timeout"] == {key: 7.0 for key in ("connect", "read", "write", "pool")}
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert "authorization" not in transport.calls[0].headers
    assert received.is_closed and transport.closed


def test_mods_route_retains_original_resolved_identity_and_both_captures() -> None:
    transport = Transport(response(MODS), response())
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = client.acquire(
            document_number="X98-10603", publication_date="1998-06-03", route="mods-start-page", start_page=30359
        )
    assert [str(call.url) for call in transport.calls] == [MODS_URL, GRANULE_URL]
    assert result.request_count == 2
    assert result.identity.source_document_number == "X98-10603"
    assert result.identity.access_id == "98-14931"
    assert result.identity.match_kind == "resolved-access-id"
    assert result.mods is not None and result.mods.body == MODS
    assert result.mods_resolution is not None and result.mods_resolution.start_page == 30359
    assert result.body.body == BODY


@pytest.mark.parametrize("status", [401, 403])
def test_credential_refusal_aborts_without_body_retry_or_fallback(status: int) -> None:
    stream = Stream(b"credential material must not be read")
    received = httpx.Response(status, stream=stream)
    transport = Transport(received)
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(CredentialRefusedError) as caught,
    ):
        acquire(client)
    assert crs_summaries.CredentialRefusedError is CredentialRefusedError
    assert len(transport.calls) == 1
    assert stream.reads == 0 and stream.closed
    assert received.is_closed and transport.closed
    refusal = caught.value.__dict__["refused_response"]
    assert isinstance(refusal, RefusedResponse) and refusal.response_bytes is None
    assert caught.value.__dict__["body_acquisition"]["requestCount"] == 1


@pytest.mark.parametrize("status", [301, 302, 400, 404])
def test_other_status_retains_exact_refusal_and_never_follows_redirect(status: int) -> None:
    received = response(b"refused", status, headers={"location": "https://example.test/elsewhere"})
    transport = Transport(received)
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError),
    ):
        try:
            acquire(client)
        except FederalRegisterBodySourceError as error:
            refusal = error.__dict__["refused_response"]
            assert refusal.response_bytes == b"refused" and refusal.request_key == GRANULE_URL
            raise
    assert len(transport.calls) == 1 and received.is_closed


@pytest.mark.parametrize("status", [429, 503])
def test_retryable_status_uses_explicit_total_budget(status: int) -> None:
    responses = [response(status=status) for _ in range(2)]
    transport = Transport(*responses)
    with (
        GovInfoBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(RetryableHTTPStatusError) as caught,
    ):
        acquire(client)
    assert len(transport.calls) == 2 and all(item.is_closed for item in responses)
    assert caught.value.__dict__["body_acquisition"]["requestCount"] == 2


def test_retry_then_mods_and_body_share_one_total_request_budget() -> None:
    transport = Transport(response(status=503), response(MODS), response())
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = client.acquire(
            document_number="X98-10603", publication_date="1998-06-03", route="mods-start-page", start_page=30359
        )
    assert result.request_count == len(transport.calls) == 3


def test_retry_can_exhaust_budget_before_body_without_misattributing_mods() -> None:
    transport = Transport(response(status=503), response(MODS))
    with (
        GovInfoBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="request budget") as caught,
    ):
        client.acquire(
            document_number="X98-10603", publication_date="1998-06-03", route="mods-start-page", start_page=30359
        )
    assert len(transport.calls) == 2
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == GRANULE_URL and refusal.response_bytes is None
    assert refusal.stage == "before-request" and refusal.unavailable_reason == "request-budget-exhausted"


def test_transport_retry_scrubs_untrusted_error_text(capsys: pytest.CaptureFixture[str]) -> None:
    transport = Transport(httpx.ConnectError("secret-key-123"), response())
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client:
        assert acquire(client).request_count == 2
    assert "secret-key-123" not in capsys.readouterr().err


def test_exhausted_transport_failure_traceback_does_not_expose_provider_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = Transport(httpx.ConnectError("secret-key-123"), httpx.ConnectError("secret-key-123"))
    with (
        GovInfoBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(ConnectionError) as caught,
    ):
        acquire(client)
    assert "secret-key-123" not in "".join(traceback.format_exception(caught.value))
    assert "secret-key-123" not in capsys.readouterr().err
    assert len(transport.calls) == 2 and transport.closed
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes is None and refusal.request_key == GRANULE_URL


@pytest.mark.parametrize("body", [b"", b"[FR Doc No: 98-00000]", b"govinfo.gov/error"])
def test_identity_refusal_retains_exact_complete_response(body: bytes) -> None:
    received = response(body)
    transport = Transport(received)
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        acquire(client)
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == body and refusal.stage == "source-validation"
    assert refusal.observed_byte_size == len(body)
    assert len(transport.calls) == 1 and received.is_closed


def test_invalid_mods_retains_mods_without_requesting_body() -> None:
    transport = Transport(response(b"invalid MODS"))
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        client.acquire(
            document_number="X98-10603", publication_date="1998-06-03", route="mods-start-page", start_page=30359
        )
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes == b"invalid MODS" and refusal.request_key == MODS_URL
    assert len(transport.calls) == 1


@pytest.mark.parametrize("declared", [False, True])
def test_over_bound_response_never_returns_or_labels_truncated_bytes_as_evidence(declared: bool) -> None:
    stream = Stream(b"a" * 30, b"b" * 30, b"unrequested tail")
    received = httpx.Response(200, stream=stream, headers={"content-length": "60"} if declared else {})
    transport = Transport(received)
    with (
        GovInfoBodyAcquirer(budget=replace(BUDGET, max_body_bytes=40), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="byte bound") as caught,
    ):
        acquire(client)
    assert stream.closed and stream.reads == (0 if declared else 2)
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes is None and refusal.unavailable_reason == "response-byte-limit"


@pytest.mark.parametrize("headers", [{"content-length": "bad"}, {"content-encoding": "gzip"}])
def test_invalid_transport_headers_refused_before_read(headers: dict[str, str]) -> None:
    stream = Stream(BODY)
    transport = Transport(httpx.Response(200, stream=stream, headers=headers))
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError),
    ):
        acquire(client)
    assert stream.closed and stream.reads == 0


def test_wrong_content_length_retains_exact_response() -> None:
    transport = Transport(response(headers={"content-length": str(len(BODY) + 1)}))
    with (
        GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="Content-Length") as caught,
    ):
        acquire(client)
    assert caught.value.__dict__["refused_response"].response_bytes == BODY


def test_short_transport_chunks_are_accumulated_through_eof() -> None:
    stream = Stream(*(BODY[index : index + 3] for index in range(0, len(BODY), 3)))
    transport = Transport(httpx.Response(200, stream=stream))
    with GovInfoBodyAcquirer(budget=replace(BUDGET, max_body_bytes=len(BODY)), transport=transport) as client:
        assert acquire(client).body.body == BODY
    assert stream.reads > 1 and stream.closed


def test_broken_body_stream_closes_before_retry_and_never_returns_partial_bytes() -> None:
    class BrokenStream(Stream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"partial"
            raise httpx.ReadError("untrusted connection text")

    broken = BrokenStream()
    transport = Transport(httpx.Response(200, stream=broken), response())
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client)
    assert broken.closed
    assert result.body.body == BODY and result.request_count == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"route": "unknown"},
        {"route": "mods-start-page"},
        {"route": "mods-start-page", "start_page": True},
        {"route": "granule", "start_page": 30359},
        {"document_number": "../escape"},
    ],
)
def test_invalid_route_or_identity_refuses_before_request(arguments: dict[str, Any]) -> None:
    transport = Transport()
    options: dict[str, Any] = {
        "document_number": "98-14931",
        "publication_date": "1998-06-03",
        "route": "granule",
        **arguments,
    }
    with GovInfoBodyAcquirer(budget=BUDGET, transport=transport) as client, pytest.raises(ValueError):
        client.acquire(**options)
    assert not transport.calls


def test_request_start_pacing_covers_retries_and_successive_acquisitions(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    starts: list[float] = []
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(acquisition.time, "sleep", lambda delay: current.__setitem__(0, current[0] + delay))

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(current[0])
        return response(status=503 if len(starts) == 1 else 200)

    with GovInfoBodyAcquirer(
        budget=replace(BUDGET, min_request_interval_seconds=0.4), transport=httpx.MockTransport(handler)
    ) as client:
        assert acquire(client).request_count == 2
        assert acquire(client).request_count == 1
    assert starts == [0.0, 0.4, 0.8]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_requests", True),
        ("max_requests", 0),
        ("max_body_bytes", MAX_EVIDENCE_BYTES + 1),
        ("max_mods_bytes", 0),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", 0),
        ("min_request_interval_seconds", -1),
        ("min_request_interval_seconds", float("nan")),
    ],
)
def test_invalid_budget_refused(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        replace(BUDGET, **{field: value})


@pytest.mark.parametrize("max_attempts", [0, -1, True, 1.5])
def test_shared_retry_rejects_invalid_explicit_attempt_count(max_attempts: int) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        retry.retry_http(
            lambda: pytest.fail("invalid budget called operation"), retryable=(RuntimeError,), max_attempts=max_attempts
        )


def test_closed_client_refuses_without_request() -> None:
    transport = Transport()
    client = GovInfoBodyAcquirer(budget=BUDGET, transport=transport)
    client.close()
    with pytest.raises(ValueError, match="closed"):
        acquire(client)
    assert not transport.calls and transport.closed
