"""Read real bzip2 bodies through controlled HTTP responses and retry failures.

Pins terminal refusals through every retry layer, credential error identity,
verified byte-range resume with a strong ETag, header validation before any
body read, advertised-length checks, repeated resumes, and whitespace handling
in opaque metadata.
"""

import bz2
import io
import urllib.error
from datetime import date
from email.message import Message

import pytest

from spicy_docs.sources.courtlistener import bulk, http
from spicy_docs.transport.credentials import CredentialRefusedError

URL = "https://storage.courtlistener.com/bulk-data/courts-2026-06-30.csv.bz2"
CSV = b'id,name,note\n1,"Court \\"A\\"",""\n2,Other,\n'
PAYLOAD = bz2.compress(CSV)
EXPECTED = [{"id": "1", "name": 'Court "A"', "note": ""}, {"id": "2", "name": "Other", "note": None}]
ETAG = '"original-object"'


class Response(io.BytesIO):
    """A scripted response that records reads, closure and header mutations."""

    def __init__(self, *, payload=PAYLOAD, offset=0, status=None, headers=None, fail_after=None, error=None, url=URL):
        super().__init__(payload[offset:])
        self.status = status if status is not None else (206 if offset else 200)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload) - offset)
        self.headers["ETag"] = ETAG
        if offset:
            self.headers["Content-Range"] = f"bytes {offset}-{len(payload) - 1}/{len(payload)}"
        for name, value in (headers or {}).items():
            del self.headers[name]
            if value is not None:
                self.headers[name] = value
        self.fail_after, self.error, self.url = fail_after, error, url
        self.read_calls = self.served = 0

    def read(self, size=-1):
        self.read_calls += 1
        if self.fail_after is not None:
            if self.served >= self.fail_after:
                raise self.error or OSError("socket interrupted")
            size = min(size, self.fail_after - self.served)
        body = super().read(size)
        self.served += len(body)
        return body

    def geturl(self):
        return self.url


@pytest.fixture
def network(monkeypatch):
    """An HTTP handler that serves queued responses and records requests."""
    pending, requests, sleeps = [], [], []

    def urlopen(request, **kwargs):
        requests.append(request)
        assert request.get_header("Accept-encoding") == "identity"
        assert request.get_header("User-agent") == http.USER_AGENT
        assert pending, "Unexpected additional request"
        outcome = pending.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    return pending, requests, sleeps


def reader(**kwargs):
    """A bulk reader wired to the scripted network."""
    return bulk.CourtListenerBulkReader("courts", dump_date=date(2026, 6, 30), **kwargs)


def error(status):
    """The expected error type for a given status."""
    return urllib.error.HTTPError(URL, status, "fixture failure", {}, io.BytesIO(b"refused"))


@pytest.mark.parametrize("status", [401, 403, 412])
@pytest.mark.parametrize("stage", ["open", "listing", "initial-read", "resume-open", "resume-read"])
def test_refusals_are_terminal_through_every_retry_layer(network, status, stage):
    """Refusals are terminal through every retry layer, with responses closed and no sleeps or extra requests."""
    pending, requests, sleeps = network
    failure = error(status)
    responses = []
    if stage in {"open", "listing"}:
        pending.append(failure)
    elif stage == "initial-read":
        responses = [Response(fail_after=0, error=failure)]
        pending.extend(responses)
    else:
        responses = [Response(fail_after=7)]
        pending.extend(responses)
        if stage == "resume-open":
            pending.append(failure)
        else:
            resumed = Response(offset=7, fail_after=0, error=failure)
            responses.append(resumed)
            pending.append(resumed)
    expected_error = CredentialRefusedError if status in {401, 403} else http.BulkTransferError
    with pytest.raises(expected_error, match=str(status)):
        bulk.list_bulk_dumps() if stage == "listing" else list(reader().iter_records())
    assert len(requests) == (2 if stage.startswith("resume") else 1)
    assert not sleeps and not pending and failure.fp.closed
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("stage", ["initial-read", "resume-read"])
def test_existing_credential_error_preserves_its_identity(network, stage):
    """An existing CredentialRefusedError propagates as the same object."""
    pending, requests, sleeps = network
    failure = CredentialRefusedError("caller refusal")
    if stage == "initial-read":
        pending.append(Response(fail_after=0, error=failure))
    else:
        pending.extend([Response(fail_after=7), Response(offset=7, fail_after=0, error=failure)])
    with pytest.raises(CredentialRefusedError) as caught:
        list(reader().iter_records())
    assert caught.value is failure and not sleeps
    assert len(requests) == (1 if stage == "initial-read" else 2)


@pytest.mark.parametrize("initial_length", [True, False])
def test_verified_resume_preserves_exact_rows_and_headers(network, initial_length):
    """A verified resume sends Range and If-Match, preserves exact rows and marks one resume."""
    pending, requests, sleeps = network
    first = Response(fail_after=7, headers={} if initial_length else {"Content-Length": None})
    resumed = Response(offset=7)
    pending.extend([first, resumed])
    current = reader()
    assert list(current.iter_records()) == EXPECTED
    assert requests[1].get_header("Range") == "bytes=7-"
    assert requests[1].get_header("If-match") == ETAG
    assert current.compressed_bytes == len(PAYLOAD) and current.resumes == 1
    assert not current.stopped_early and first.closed and resumed.closed and not sleeps


@pytest.mark.parametrize("etag", [None, 'W/"original-object"'])
def test_uninterrupted_read_needs_no_strong_etag_but_resume_does(network, etag):
    """An uninterrupted read needs no strong ETag, but a resume without one refuses."""
    pending, requests, sleeps = network
    pending.append(Response(headers={"ETag": etag}))
    assert list(reader().iter_records()) == EXPECTED
    requests.clear()
    first = Response(headers={"ETag": etag}, fail_after=0)
    pending.append(first)
    with pytest.raises(http.BulkTransferError, match="strong original ETag"):
        list(reader().iter_records())
    assert len(requests) == 1 and not sleeps and first.closed


@pytest.mark.parametrize("etag", ["", "unquoted", '"a", "b"', 'w/"a"', '"control\x01"'])
def test_malformed_initial_etag_refuses_without_reading(network, etag):
    """A malformed initial ETag refuses before any body read."""
    initial = Response(headers={"ETag": etag})
    network[0].append(initial)
    with pytest.raises(http.BulkTransferError, match="malformed initial ETag"):
        list(reader().iter_records())
    assert initial.closed and initial.read_calls == 0 and len(network[1]) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "missing-range",
        "bad-range",
        "wrong-start",
        "short-end",
        "unknown-total",
        "changed-total",
        "missing-etag",
        "changed-etag",
        "weak-etag",
        "encoding",
        "length",
        "duplicate-range",
        "duplicate-etag",
        "url",
    ],
)
def test_invalid_resume_headers_refuse_before_reading_any_resumed_body(network, mutation):
    """Invalid resume headers refuse before any resumed body is read."""
    pending, requests, sleeps = network
    first, resumed = Response(fail_after=7), Response(offset=7)
    if mutation == "status":
        resumed.status = 200
    elif mutation == "url":
        resumed.url += "?different-object"
    elif mutation.startswith("duplicate"):
        name = "Content-Range" if mutation == "duplicate-range" else "ETag"
        resumed.headers[name] = resumed.headers[name]
    else:
        replacements = {
            "missing-range": ("Content-Range", None),
            "bad-range": ("Content-Range", "bytes nonsense"),
            "wrong-start": ("Content-Range", f"bytes 8-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"),
            "short-end": ("Content-Range", f"bytes 7-{len(PAYLOAD) - 2}/{len(PAYLOAD)}"),
            "unknown-total": ("Content-Range", f"bytes 7-{len(PAYLOAD) - 1}/*"),
            "changed-total": ("Content-Range", f"bytes 7-{len(PAYLOAD)}/{len(PAYLOAD) + 1}"),
            "missing-etag": ("ETag", None),
            "changed-etag": ("ETag", '"changed"'),
            "weak-etag": ("ETag", 'W/"original-object"'),
            "encoding": ("Content-Encoding", "gzip"),
            "length": ("Content-Length", str(len(PAYLOAD))),
        }
        name, value = replacements[mutation]
        del resumed.headers[name]
        if value is not None:
            resumed.headers[name] = value
    pending.extend([first, resumed])
    with pytest.raises(http.BulkTransferError):
        list(reader().iter_records())
    assert len(requests) == 2 and not sleeps
    assert first.closed and resumed.closed and resumed.read_calls == 0


@pytest.mark.parametrize("mutation", ["status", "encoding", "length", "range", "duplicate-length"])
def test_invalid_initial_headers_close_before_any_body_read(network, mutation):
    """Invalid initial headers close before any body read and mark the run stopped early."""
    pending, requests, sleeps = network
    initial = Response()
    if mutation == "status":
        initial.status = 206
    elif mutation == "duplicate-length":
        initial.headers["Content-Length"] = initial.headers["Content-Length"]
    else:
        name, value = {
            "encoding": ("Content-Encoding", "gzip"),
            "length": ("Content-Length", "-1"),
            "range": ("Content-Range", f"bytes 0-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"),
        }[mutation]
        del initial.headers[name]
        initial.headers[name] = value
    pending.append(initial)
    current = reader()
    with pytest.raises(http.BulkTransferError):
        list(current.iter_records())
    assert initial.closed and initial.read_calls == 0 and len(requests) == 1 and not sleeps
    assert current.stopped_early


@pytest.mark.parametrize("length", [len(PAYLOAD) - 1, len(PAYLOAD) + 1])
def test_complete_bzip2_member_does_not_hide_an_advertised_length_mismatch(network, length):
    """A complete bzip2 member does not hide a mismatch against the advertised object length."""
    pending, _, _ = network
    initial = Response(headers={"Content-Length": str(length)})
    pending.append(initial)
    current = reader()
    with pytest.raises(http.BulkTransferError, match="advertised object length"):
        list(current.iter_records())
    assert current.stopped_early and initial.closed


def test_unknown_initial_length_resume_establishes_a_total_checked_at_eof(network):
    """An unknown initial length is established by the resume and checked at EOF."""
    pending, _, _ = network
    initial = Response(fail_after=7, headers={"Content-Length": None})
    resumed = Response(
        offset=7, headers={"Content-Length": None, "Content-Range": f"bytes 7-{len(PAYLOAD)}/{len(PAYLOAD) + 1}"}
    )
    pending.extend([initial, resumed])
    with pytest.raises(http.BulkTransferError, match="advertised object length"):
        list(reader().iter_records())
    assert initial.closed and resumed.closed


def test_missing_length_without_resume_remains_supported(network):
    """A missing length without resume remains supported."""
    network[0].append(Response(headers={"Content-Length": None, "ETag": None}))
    assert list(reader().iter_records()) == EXPECTED


@pytest.mark.parametrize("limits", [{"max_compressed_bytes": 7}, {"max_records": 1}])
def test_intentional_limits_do_not_claim_or_require_natural_eof(network, limits):
    """Intentional limits neither claim nor require natural EOF."""
    initial = Response()
    network[0].append(initial)
    current = reader(**limits)
    rows = list(current.iter_records())
    assert rows == ([] if "max_compressed_bytes" in limits else EXPECTED[:1])
    assert current.stopped_early and initial.closed
    if "max_compressed_bytes" in limits:
        assert initial.served == 7 and current.compressed_bytes == 7


def test_resume_attempts_are_not_multiplied_by_the_open_retry_loop(network):
    """Resume attempts are not multiplied by the open retry loop."""
    pending, requests, sleeps = network
    initial = Response(fail_after=7)
    pending.append(initial)
    pending.extend(OSError("still unavailable") for _ in range(http.MAX_ATTEMPTS))
    with pytest.raises(RuntimeError, match="could not resume"):
        list(reader().iter_records())
    assert len(requests) == 1 + http.MAX_ATTEMPTS and len(sleeps) == http.MAX_ATTEMPTS - 1
    assert not pending and initial.closed


def test_initial_transient_status_closes_each_response_and_retries(network):
    """An initial transient status closes each response and retries up to MAX_ATTEMPTS."""
    pending, requests, sleeps = network
    failures = [error(503) for _ in range(http.MAX_ATTEMPTS - 1)]
    final = Response()
    pending.extend([*failures, final])
    assert list(reader().iter_records()) == EXPECTED
    assert len(requests) == http.MAX_ATTEMPTS and len(sleeps) == http.MAX_ATTEMPTS - 1
    assert all(failure.fp.closed for failure in failures) and final.closed


@pytest.mark.parametrize("status", [401, 403, 412])
def test_http_refusal_survives_its_handle_close_failure(network, status):
    """An HTTP refusal survives a failure while closing its handle."""
    failure = error(status)

    def broken_close():
        failure.fp.close()
        raise OSError("closing failed")

    failure.close = broken_close
    network[0].append(failure)
    expected_error = CredentialRefusedError if status in {401, 403} else http.BulkTransferError
    with pytest.raises(expected_error, match=str(status)):
        list(reader().iter_records())
    assert len(network[1]) == 1 and not network[2] and failure.fp.closed


def test_rejected_resume_keeps_protocol_error_when_close_fails(network):
    """A rejected resume keeps its protocol error even when closing fails."""

    class BrokenClose(Response):
        def close(self):
            super().close()
            raise OSError("closing failed")

    initial = BrokenClose(fail_after=7)
    resumed = BrokenClose(offset=7, headers={"ETag": '"changed"'})
    network[0].extend([initial, resumed])
    with pytest.raises(http.BulkTransferError, match="ETag differs"):
        list(reader().iter_records())
    assert initial.closed and resumed.closed and resumed.read_calls == 0
    assert len(network[1]) == 2 and not network[2]


def test_repeated_resumes_keep_original_etag_and_current_offset(network):
    """Repeated resumes keep the original ETag and advance the byte offset."""
    responses = [Response(fail_after=7), Response(offset=7, fail_after=7), Response(offset=14)]
    network[0].extend(responses)
    current = reader()
    assert list(current.iter_records()) == EXPECTED
    assert [request.get_header("Range") for request in network[1]] == [None, "bytes=7-", "bytes=14-"]
    assert all(request.get_header("If-match") == ETAG for request in network[1][1:])
    assert current.resumes == 2 and all(response.closed for response in responses)


def test_zero_byte_failure_still_requires_verified_partial_response(network):
    """A zero-byte failure still requires a verified partial response."""
    initial = Response(fail_after=0)
    resumed = Response(status=206, headers={"Content-Range": f"bytes 0-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"})
    network[0].extend([initial, resumed])
    assert list(reader().iter_records()) == EXPECTED
    assert network[1][1].get_header("Range") == "bytes=0-"
    assert network[1][1].get_header("If-match") == ETAG


def test_learned_total_cannot_change_on_a_later_resume(network):
    """A learned total cannot change on a later resume."""
    first = Response(fail_after=7, headers={"Content-Length": None})
    second = Response(offset=7, fail_after=7)
    third = Response(
        offset=14, headers={"Content-Length": None, "Content-Range": f"bytes 14-{len(PAYLOAD)}/{len(PAYLOAD) + 1}"}
    )
    network[0].extend([first, second, third])
    with pytest.raises(http.BulkTransferError, match="total differs"):
        list(reader().iter_records())
    assert all(response.closed for response in (first, second, third)) and third.read_calls == 0


def test_http_space_and_tab_are_removed_without_changing_the_opaque_etag(network):
    """HTTP spaces and tabs are removed without changing the opaque ETag."""
    tag = '"literal\\opaque"'
    first = Response(
        fail_after=7,
        headers={
            "ETag": " \t" + tag + "\t ",
            "Content-Length": f"\t{len(PAYLOAD)} ",
            "Content-Encoding": " identity\t",
        },
    )
    second = Response(
        offset=7,
        headers={
            "ETag": "\t" + tag + " ",
            "Content-Length": f" {len(PAYLOAD) - 7}\t",
            "Content-Range": f" \tbytes 7-{len(PAYLOAD) - 1}/{len(PAYLOAD)} \t",
            "Content-Encoding": "\tIDENTITY ",
        },
    )
    network[0].extend([first, second])
    assert list(reader().iter_records()) == EXPECTED
    assert network[1][1].get_header("If-match") == tag
    assert first.closed and second.closed


@pytest.mark.parametrize(
    ("name", "value"),
    [("ETag", ETAG + "\u00a0"), ("Content-Length", str(len(PAYLOAD)) + "\r\n"), ("Content-Encoding", "\u00a0identity")],
)
def test_non_http_whitespace_is_not_normalized_into_valid_metadata(network, name, value):
    """Non-HTTP whitespace is not normalized into valid metadata."""
    first = Response(headers={name: value})
    network[0].append(first)
    with pytest.raises(http.BulkTransferError):
        list(reader().iter_records())
    assert first.closed and first.read_calls == 0 and len(network[1]) == 1
