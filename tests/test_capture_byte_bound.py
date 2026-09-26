"""A body refused at the byte bound carries the Content-Length its response stated.

A response whose stated length is past the bound is refused before any body byte
is read, so it has no observed size; the stated one is what a caller compares the
next answer with (GovInfo's 1946 hearing parts state 312,487,940 and 373,504,330
bytes against a 24 MiB bound). A stream that overruns the bound keeps its observed
count and any length it stated. Retention writes the stated size only where one
was stated, so every other refusal record is unchanged.
"""

from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response, retain_refused_response
from spicy_docs.transport.capture import BoundedHttpCapture
from spicy_docs.transport.credentials import CredentialRefusedError

URL = "https://www.govinfo.gov/content/pkg/CHRG-79jhrg79716p11/pdf/CHRG-79jhrg79716p11.pdf"
PART_11_BYTES = 312_487_940


class Unread(httpx.SyncByteStream):
    """A body that fails the test if any of it is read."""

    def __iter__(self):
        raise AssertionError("a body past its stated bound must not be read")
        yield b""  # pragma: no cover


def _refusal(response: httpx.Response, *, max_bytes: int = 1024, error=ValueError) -> RefusedResponse:
    client = BoundedHttpCapture(
        max_requests=1,
        timeout_seconds=1,
        min_request_interval_seconds=0,
        user_agent="test",
        error_type=ValueError,
        transport=httpx.MockTransport(lambda _request: response),
        clock=lambda: datetime.now(UTC),
        retain_refusal_bodies=True,
    )
    try:
        with pytest.raises(error, match="byte bound" if error is ValueError else None) as raised:
            client.capture(URL, max_bytes=max_bytes)
    finally:
        client.close()
    return raised.value.refused_response


def test_a_stated_length_past_the_bound_is_carried_and_no_body_is_read():
    refused = _refusal(
        httpx.Response(200, stream=Unread(), headers={"content-length": str(PART_11_BYTES)}),
        max_bytes=24 * 1024 * 1024,
    )
    assert refused.unavailable_reason == "response-byte-limit"
    assert (refused.stated_byte_size, refused.observed_byte_size) == (PART_11_BYTES, None)


@pytest.mark.parametrize("stated", [None, 100], ids=["no-length", "understated"])
def test_a_stream_that_overruns_the_bound_keeps_its_observed_count_and_any_stated_length(stated):
    """Reading stops one byte past the bound; a length the response stated travels beside that count."""
    headers = {} if stated is None else {"content-length": str(stated)}
    refused = _refusal(httpx.Response(200, stream=httpx.ByteStream(b"x" * 2048), headers=headers))
    assert refused.unavailable_reason == "response-byte-limit"
    assert (refused.observed_byte_size, refused.stated_byte_size) == (1025, stated)


def test_an_oversize_access_refusal_carries_its_stated_length():
    body = b"denied " * 300
    refused = _refusal(
        httpx.Response(403, stream=httpx.ByteStream(body), headers={"content-length": str(len(body))}),
        error=CredentialRefusedError,
    )
    assert refused.unavailable_reason == "response-byte-limit"
    assert refused.stated_byte_size == len(body) and refused.observed_byte_size is not None


def test_retention_writes_the_stated_size_only_where_one_was_stated(tmp_path):
    stated, unstated = ValueError("over"), ValueError("over")
    attach_refused_response(
        stated,
        RefusedResponse(
            URL, "transport", None, "application/octet-stream", "response-byte-limit", stated_byte_size=PART_11_BYTES
        ),
    )
    attach_refused_response(
        unstated, RefusedResponse(URL, "transport", None, "application/octet-stream", "response-byte-limit", 2048)
    )
    assert retain_refused_response(stated, store=tmp_path, max_bytes=100)["stated_byte_size"] == PART_11_BYTES
    assert set(retain_refused_response(unstated, store=tmp_path, max_bytes=100)) == {
        "request_key",
        "stage",
        "media_type",
        "unavailable_reason",
        "observed_byte_size",
    }
