"""A known access refusal stops immediately, including failed and oversize bodies.

Pins that complete, empty, small and exactly-at-bound refusal bodies stay exact;
an oversize stream stops before its tail and never retains a prefix; observed
size counts actual chunks; a failed body never retries; and a credentialed
refusal reads no body.
"""

import gzip
from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs.transport.capture import BoundedHttpCapture
from spicy_docs.transport.credentials import CredentialRefusedError

URL = "https://example.gov/public"


class Stream(httpx.SyncByteStream):
    """A one-shot response stream that counts reads and records closure."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


def capture(stream, *, max_bytes=10, keyless=True, status=403, headers=None):
    """Capture one refusal stream and return the raised error's refusal evidence."""
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, stream=stream, headers=headers or {"content-type": "text/plain"})

    client = BoundedHttpCapture(
        max_requests=3,
        timeout_seconds=1,
        min_request_interval_seconds=0,
        user_agent="test",
        error_type=ValueError,
        transport=httpx.MockTransport(respond),
        clock=lambda: datetime.now(UTC),
        retain_refusal_bodies=keyless,
    )
    try:
        with pytest.raises(CredentialRefusedError) as raised:
            client.capture(URL, max_bytes=max_bytes)
    finally:
        client.close()
    assert len(calls) == 1
    assert stream.closed
    return raised.value.refused_response


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("body", [b"", b"denied", b"0123456789"])
def test_complete_empty_small_and_exact_bound_bodies_remain_exact(status, body):
    """Empty, small and exactly-at-bound bodies are retained byte-for-byte with observed sizes and an access-refused
    reason.
    """
    result = capture(Stream([body]), status=status)
    assert result.response_bytes == body
    assert result.observed_byte_size == len(body)
    assert result.unavailable_reason == "access-refused"


def test_oversize_stream_stops_before_tail_and_never_retains_a_prefix():
    """An oversize stream reads two chunks, retains no bytes, records the observed size and a response-byte-limit
    reason.
    """
    stream = Stream([b"123456", b"78901", AssertionError("must not read the tail")])
    result = capture(stream)
    assert stream.reads == 2
    assert result.response_bytes is None
    assert result.observed_byte_size == 11
    assert result.unavailable_reason == "response-byte-limit"


def test_observed_size_counts_actual_chunks_not_an_invented_total():
    """Observed size counts chunks actually read (131072), not an invented content length."""
    result = capture(Stream([b"x" * 65536, b"y" * 65536, AssertionError("tail")]), max_bytes=100_000)
    assert result.response_bytes is None
    assert result.observed_byte_size == 131072


def test_failed_refusal_body_never_retries_or_becomes_partial_evidence():
    """A failed refusal body is neither retried nor kept as partial evidence."""
    stream = Stream([b"small prefix", httpx.ReadError("untrusted remote detail")])
    result = capture(stream, max_bytes=100)
    assert result.response_bytes is None
    assert result.unavailable_reason == "response-unavailable"


def test_credentialed_refusal_never_reads_the_body():
    """A credentialed refusal reads zero body chunks."""
    stream = Stream([AssertionError("body may contain credentials")])
    result = capture(stream, keyless=False)
    assert stream.reads == 0
    assert result.response_bytes is None


def test_encoded_refusal_is_bounded_raw_evidence_without_decompression():
    """An encoded refusal is retained as raw bounded bytes under application/octet-stream, never decompressed."""
    body = gzip.compress(b"x" * 1_000_000)
    result = capture(Stream([body]), max_bytes=2048, headers={"content-type": "text/plain", "content-encoding": "gzip"})
    assert result.response_bytes == body
    assert result.observed_byte_size == len(body)
    assert result.media_type == "application/octet-stream"
