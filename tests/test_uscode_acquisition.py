"""OLRC U.S. Code requests preserve exact responses, bounds, and refusal evidence.

Title, corpus, annual, popular-names, and Table 3 routes capture original bytes; a 302 document-not-found is a
refusal rather than an absence; byte, entry, and expansion bounds refuse with the capture retained; and Table III
absence is read from the chain its pages link, never from a dropped answer's bytes."""

import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.uscode import ReleasePoint, TitleSelection, UsCodeSourceError, iter_table3_chain
from spicy_docs.sources.uscode.acquisition import (
    UsCodeAcquirer,
    UsCodeAcquisitionBudget,
    UsCodeSourceUnavailableError,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"
TITLE_ZIP = (FIXTURES / "xml_usc01@119-103.zip").read_bytes()
ANNUAL_HTML = (FIXTURES / "annual-2024usc01-head.htm").read_bytes()
POPULAR_NAMES = (FIXTURES / "popularnames-head.htm").read_bytes()
TABLE3_PAGE = (FIXTURES / "table3-1955_360-head.htm").read_bytes()
TABLE3_TRUNCATED = (FIXTURES / "table3-100_234-truncated.htm").read_bytes()
#: 119-69 names 119-72 next and 119-72 names 119-73: 119-70 and 119-71 have no page.
CHAIN = [(FIXTURES / f"table3-119_{number}-head.htm").read_bytes() for number in (69, 72, 73)]
BULK_XML = (FIXTURES / "table3-fulldump-head.xml").read_bytes()

CURRENT = ReleasePoint(119, 103)
TITLE = TitleSelection(CURRENT, "01")
BUDGET = UsCodeAcquisitionBudget(3, 1 << 20, 7, 0)
NOW = datetime(2026, 9, 14, tzinfo=UTC)
DOWNLOAD = "https://uscode.house.gov/download/releasepoints/us/pl/119/103"


def archive(*members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


with zipfile.ZipFile(io.BytesIO(TITLE_ZIP)) as _archive:
    TITLE_XML = _archive.read("usc01.xml")
ANNUAL_ZIP = archive(("2024/2024usc01.htm", ANNUAL_HTML))
BULK_ZIP = archive(("fulldump@119-73.xml", BULK_XML))
CORPUS_ZIP = archive(("usc01.xml", TITLE_XML))


def response(body=TITLE_ZIP, status=200, *, content_type=None, **headers):
    """The download routes send no Content-Type at all, so the default sends none."""
    if content_type is not None:
        headers["content-type"] = content_type
    return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)


class Dropped(httpx.SyncByteStream):
    """The body in two chunks, then the connection closed before the body ended, as OLRC closes it."""

    def __init__(self, body):
        self.body = body

    def __iter__(self):
        yield self.body[:4096]
        yield self.body[4096:]
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")


def page(body, *, dropped=False):
    stream = Dropped(body) if dropped else httpx.ByteStream(body)
    return httpx.Response(200, stream=stream, headers={"content-type": "text/html;charset=UTF-8"})


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


def test_exact_capture_and_native_metadata_for_one_title():
    transport = Transport(response())
    with UsCodeAcquirer(budget=BUDGET, transport=transport, clock=lambda: NOW) as source:
        result = source.acquire_title(TITLE)
    assert result.capture.body == TITLE_ZIP
    assert result.result.xml_bytes == TITLE_XML
    assert result.operation == "release-point-title"
    assert result.selection == {"release_point": "119-103", "title": "01"}
    assert result.result.entry.metadata.doc_number == "1"
    assert result.result.entry.metadata.release_point == "Online@119-103"
    assert result.capture.requested_url == f"{DOWNLOAD}/xml_usc01@119-103.zip"
    assert result.capture.resolved_url == result.capture.requested_url
    assert result.capture.observed_at == "2026-09-14T00:00:00Z"
    assert result.capture.byte_size == len(TITLE_ZIP)
    assert result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].method == "GET"
    assert transport.calls[0].headers["accept-encoding"] == "identity"


def test_a_download_route_answering_without_a_content_type_is_still_proved_from_its_bytes():
    # Measured 2026-09-14: the zip routes send neither Content-Type nor
    # Content-Length. The header's absence is allowed; the shape is not assumed.
    transport = Transport(response(), response(TITLE_ZIP, content_type="application/zip"))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        assert source.acquire_title(TITLE).capture.content_type is None
        assert source.acquire_title(TITLE).capture.content_type == "application/zip"


@pytest.mark.parametrize(
    "kind,body,expanded", [("corpus", CORPUS_ZIP, len(TITLE_XML)), ("annual", ANNUAL_ZIP, len(ANNUAL_HTML))]
)
def test_acquired_archives_honor_the_selected_aggregate_expansion_bound(kind, body, expanded):
    transport = Transport(response(body))
    with (
        UsCodeAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UsCodeSourceError, match="max_total_bytes") as raised,
    ):
        if kind == "corpus":
            source.acquire_corpus(CURRENT, max_total_bytes=expanded - 1)
        else:
            source.acquire_annual_archive(2024, max_total_bytes=expanded - 1)
    assert raised.value.capture.body == body
    assert len(transport.calls) == 1


def test_corpus_without_a_title_is_refused_with_its_exact_capture():
    body = archive(("empty/", b""))
    transport = Transport(response(body))
    with (
        UsCodeAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UsCodeSourceError, match="holds no title member") as raised,
    ):
        source.acquire_corpus(CURRENT)
    assert raised.value.capture.body == body
    assert raised.value.refused_response.response_bytes == body
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "operation,args,kwargs,body,content_type,expected_url",
    [
        ("title", (TITLE,), {}, TITLE_ZIP, None, f"{DOWNLOAD}/xml_usc01@119-103.zip"),
        ("corpus", (CURRENT,), {}, CORPUS_ZIP, None, f"{DOWNLOAD}/xml_uscAll@119-103.zip"),
        (
            "annual_archive",
            (2024,),
            {},
            ANNUAL_ZIP,
            None,
            "https://uscode.house.gov/download/annualhistoricalarchives/XHTML/2024.zip",
        ),
        (
            "popular_names",
            (),
            {},
            POPULAR_NAMES,
            "text/html;charset=UTF-8",
            "https://uscode.house.gov/popularnames/popularnames.htm",
        ),
        (
            "table3_act",
            ("1955:360",),
            {},
            TABLE3_PAGE,
            "text/html;charset=UTF-8",
            "https://uscode.house.gov/table3/1955_360.htm",
        ),
        ("table3_bulk", (), {}, BULK_ZIP, None, "https://uscode.house.gov/table3/table3-xml-bulk.zip"),
    ],
)
def test_every_route_captures_original_bytes(operation, args, kwargs, body, content_type, expected_url):
    transport = Transport(response(body, content_type=content_type))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        result = getattr(source, "acquire_" + operation)(*args, **kwargs)
    assert result.capture.body == body
    assert result.capture.requested_url == expected_url
    assert result.request_count == 1


@pytest.mark.parametrize("status", [404, 410])
def test_exact_unavailable_response_is_retained_without_another_route(status):
    transport = Transport(response(b"unavailable here", status))
    with (
        UsCodeAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UsCodeSourceUnavailableError) as raised,
    ):
        source.acquire_annual_archive(1994)
    assert raised.value.capture.body == b"unavailable here"
    assert raised.value.refused_response.response_bytes == b"unavailable here"
    assert raised.value.uscode_acquisition == {
        "operation": "annual-archive",
        "selection": {"year": 1994},
        "requestCount": 1,
        "budget": {"max_requests": 3, "max_bytes": 1 << 20, "timeout_seconds": 7, "min_request_interval_seconds": 0},
    }
    assert len(transport.calls) == 1


def test_a_title_the_publisher_lists_but_does_not_serve_is_a_refusal_not_an_absence():
    # Measured 2026-09-14: title 53 answers 302 to /docnotfound.xhtml, never 404.
    transport = Transport(response(b"", 302, location="/docnotfound.xhtml?omitHeader=true"))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UsCodeSourceError) as raised:
        source.acquire_title(TitleSelection(CURRENT, "53"))
    assert not isinstance(raised.value, UsCodeSourceUnavailableError)
    assert "302" in str(raised.value)
    assert raised.value.uscode_acquisition["selection"] == {"release_point": "119-103", "title": "53"}


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_aborts_and_keeps_the_keyless_answer(status):
    # OLRC is keyless, so a 401/403 body is the publisher's answer, kept as evidence; the call still aborts.
    transport = Transport(response(b"<html>denied</html>", status, content_type="text/html"))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.acquire_popular_names()
    assert raised.value.refused_response.response_bytes == b"<html>denied</html>"
    assert raised.value.uscode_acquisition["requestCount"] == len(transport.calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        response(b"<html>Document not found</html>", content_type="text/html"),
        response(b"<html>Document not found</html>"),
        response(archive(("usc02.xml", TITLE_XML))),
        response(b""),
        response(TITLE_ZIP[:-5]),
        response(status=302, location="https://example.invalid/other.zip"),
        response(**{"content-length": str(len(TITLE_ZIP) + 1)}),
        response(POPULAR_NAMES, content_type="text/html"),
    ],
)
def test_wrong_shape_identity_redirect_or_incomplete_response_never_succeeds(answer):
    transport = Transport(answer)
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UsCodeSourceError) as raised:
        source.acquire_title(TITLE)
    assert len(transport.calls) == 1
    assert raised.value.refused_response.response_bytes is not None


def test_a_dropped_table3_answer_is_retried_and_keeps_its_bytes_as_evidence_never_as_an_absence():
    # An act without a page answers 200, the site template up to 16 KB, and a dropped connection. A served page
    # dropped at the same point is byte for byte the same, so this is a transport failure like any other.
    transport = Transport(*(page(TABLE3_TRUNCATED, dropped=True) for _ in range(BUDGET.max_requests)))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ConnectionError) as raised:
        source.acquire_table3_act("100-234")
    assert len(transport.calls) == raised.value.uscode_acquisition["requestCount"] == BUDGET.max_requests
    evidence = raised.value.refused_response
    assert (evidence.response_bytes, evidence.observed_byte_size) == (TABLE3_TRUNCATED, len(TABLE3_TRUNCATED))
    assert (evidence.stage, evidence.media_type, evidence.unavailable_reason) == (
        "transport",
        "text/html",
        "connection-dropped",
    )
    assert raised.value.uscode_acquisition["selection"] == {"key": "100-234"}


def test_other_routes_keep_no_bytes_from_a_dropped_body():
    transport = Transport(*(page(POPULAR_NAMES, dropped=True) for _ in range(BUDGET.max_requests)))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ConnectionError) as raised:
        source.acquire_popular_names()
    assert len(transport.calls) == BUDGET.max_requests
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.refused_response.unavailable_reason == "response-unavailable"


def walk(transport, start="119-69", **kwargs):
    """The acquisitions a chain walk yields and the reason it returns, through the real acquirer."""
    walked = []
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        chain = iter_table3_chain(source.acquire_table3_act, start, **{"max_acts": 10, **kwargs})
        while True:
            try:
                walked.append(next(chain))
            except StopIteration as end:
                return [acquired.result.key for acquired in walked], end.value


def test_the_chain_follows_the_links_the_pages_state_and_stops_at_the_tables_currency():
    transport = Transport(*(page(body) for body in CHAIN))
    assert walk(transport) == (["119-69", "119-72", "119-73"], "names an act past the release point it states")
    assert [call.url.path for call in transport.calls] == [
        "/table3/119_69.htm",
        "/table3/119_72.htm",
        "/table3/119_73.htm",
    ]
    # 119-73 states the table current through 119-73 and names 119-74 next; on 2026-09-24 that act answered only
    # the site template, so the walk does not ask for it.


NEXT_73 = b'href="119_73.htm">119&ndash;73'


@pytest.mark.parametrize(
    ("linked", "reason"),
    [
        (None, "names no next public law"),
        (b'href="120_1.htm">120&ndash;1', "names an act in another Congress"),
        (b'href="119_69.htm">119&ndash;69', "names an act that does not follow it"),
        (b'href="1955_360.htm">1955:360', "names no next public law"),
    ],
    ids=["no-next-act", "another-congress", "not-following", "a-chapter-key"],
)
def test_the_chain_ends_at_a_link_it_cannot_follow_without_asking_for_it(linked, reason):
    middle = (
        CHAIN[1].replace(b"class='nextact'", b"class='removed'")
        if linked is None
        else CHAIN[1].replace(NEXT_73, linked)
    )
    transport = Transport(page(CHAIN[0]), page(middle))
    assert walk(transport) == (["119-69", "119-72"], reason)
    assert len(transport.calls) == 2


def test_the_callers_own_bound_and_max_acts_end_the_walk_before_a_request():
    transport = Transport(*(page(body) for body in CHAIN))
    assert walk(transport, within={"119-69", "119-72"}) == (
        ["119-69", "119-72"],
        "names an act outside the caller's bound",
    )
    transport = Transport(*(page(body) for body in CHAIN))
    assert walk(transport, max_acts=2) == (["119-69", "119-72"], "reached max_acts")
    assert len(transport.calls) == 2


def test_a_chain_page_dropped_mid_body_is_retried_and_read():
    transport = Transport(page(CHAIN[0]), page(CHAIN[1][:2000], dropped=True), page(CHAIN[1]), page(CHAIN[2]))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        walked = list(iter_table3_chain(source.acquire_table3_act, "119-69", max_acts=10))
    assert [acquired.result.key for acquired in walked] == ["119-69", "119-72", "119-73"]
    assert [acquired.request_count for acquired in walked] == [1, 2, 1]


def test_a_chain_page_that_keeps_dropping_ends_the_walk_as_a_transport_failure():
    answers = [page(CHAIN[0])] + [page(CHAIN[1][:2000], dropped=True) for _ in range(BUDGET.max_requests)]
    transport = Transport(*answers)
    walked = []
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ConnectionError) as raised:
        walked.extend(iter_table3_chain(source.acquire_table3_act, "119-69", max_acts=10))
    assert [acquired.result.key for acquired in walked] == ["119-69"]
    assert len(transport.calls) == 1 + BUDGET.max_requests
    assert raised.value.refused_response.response_bytes == CHAIN[1][:2000]
    assert raised.value.uscode_acquisition["selection"] == {"key": "119-72"}


@pytest.mark.parametrize(("start", "max_acts"), [("119_69", 1), ("1955:360", 1), ("119-69", 0), ("119-69", True)])
def test_a_walk_with_a_bad_start_or_bound_makes_no_request(start, max_acts):
    transport = Transport()
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UsCodeSourceError):
        next(iter_table3_chain(source.acquire_table3_act, start, max_acts=max_acts))
    assert not transport.calls


def test_a_page_route_refuses_a_zip_and_an_archive_route_refuses_a_page():
    transport = Transport(response(TITLE_ZIP, content_type="application/zip"), response(POPULAR_NAMES))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(UsCodeSourceError, match="Content-Type"):
            source.acquire_popular_names()
        with pytest.raises(UsCodeSourceError, match="local file header"):
            source.acquire_table3_bulk()


def test_an_invalid_table3_key_never_makes_a_request():
    transport = Transport()
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(UsCodeSourceError):
        source.acquire_table3_act("1955-360")
    assert not transport.calls


def test_retries_consume_request_budget_and_next_operation_starts_a_new_count():
    transport = Transport(response(status=503), response(), response())
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        first = source.acquire_title(TITLE)
        second = source.acquire_title(TITLE)
    assert (first.request_count, second.request_count) == (2, 1)
    assert len(transport.calls) == 3


def test_exhausted_transient_response_does_not_establish_source_absence():
    transport = Transport(response(status=503), response(status=503))
    with (
        UsCodeAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as source,
        pytest.raises(RetryableHTTPStatusError) as raised,
    ):
        source.acquire_corpus(CURRENT)
    assert len(transport.calls) == raised.value.uscode_acquisition["requestCount"] == 2
    assert raised.value.refused_response.response_bytes is None


def test_effective_byte_allowance_is_recorded_and_cannot_raise_the_client_limit():
    transport = Transport(response(), response())
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        small = source.acquire_title(TITLE, max_bytes=len(TITLE_ZIP))
        large = source.acquire_title(TITLE, max_bytes=BUDGET.max_bytes * 2)
    assert small.budget.max_bytes == len(TITLE_ZIP)
    assert large.budget == BUDGET


@pytest.mark.parametrize("with_length", [False, True])
def test_byte_overrun_has_no_successful_partial_capture(with_length):
    headers = {"content-length": str(len(TITLE_ZIP))} if with_length else {}
    transport = Transport(response(**headers))
    with (
        UsCodeAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UsCodeSourceError, match="byte bound") as raised,
    ):
        source.acquire_title(TITLE, max_bytes=len(TITLE_ZIP) - 1)
    assert raised.value.refused_response.response_bytes is None
    assert raised.value.uscode_acquisition["budget"]["max_bytes"] == len(TITLE_ZIP) - 1


def test_archive_and_page_bounds_are_passed_through():
    transport = Transport(response(), response(BULK_ZIP), response(POPULAR_NAMES, content_type="text/html"))
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(UsCodeSourceError, match="max_entry_bytes"):
            source.acquire_title(TITLE, max_entry_bytes=len(TITLE_XML) - 1)
        with pytest.raises(UsCodeSourceError, match="max_member_bytes"):
            source.acquire_table3_bulk(max_member_bytes=len(BULK_XML) - 1)
        with pytest.raises(UsCodeSourceError, match="max_entries"):
            source.acquire_popular_names(max_entries=1)


def test_configuration_cannot_diverge_and_closed_client_cannot_make_requests():
    transport = Transport()
    source = UsCodeAcquirer(budget=BUDGET, transport=transport)
    with pytest.raises(AttributeError):
        source.budget = replace(BUDGET, max_requests=20)
    source.close()
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.acquire_title(TITLE)
    assert not transport.calls
    with pytest.raises(TypeError):
        UsCodeAcquirer(budget=(3, 65536, 7, 0), transport=transport)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_byte_allowance_never_makes_a_request(limit):
    transport = Transport()
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(ValueError):
        source.acquire_title(TITLE, max_bytes=limit)
    assert not transport.calls


@pytest.mark.parametrize(
    "fields",
    [
        {"max_requests": True},
        {"max_requests": 0},
        {"max_bytes": 512 * 1024**2 + 1},
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
    transport = Transport(response(TITLE_ZIP, **{"content-encoding": "gzip"}))
    with (
        UsCodeAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(UsCodeSourceError, match="encoding"),
    ):
        source.acquire_title(TITLE)
    assert transport.calls[0].headers["accept-encoding"] == "identity"
