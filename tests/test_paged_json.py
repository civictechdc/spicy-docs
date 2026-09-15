"""The shared paged-JSON reader keeps exact pages and refuses silent or inconsistent ends."""

import json
from dataclasses import replace

import httpx
import pytest

from spicy_docs.sources.paged_json import (
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
    PagedJsonUnavailableError,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FAMILY = JsonPageFamily(
    name="example",
    label="Example",
    host="api.example.gov",
    next_path=("paging", "next"),
    count_path=("paging", "count"),
)
BUDGET = PagedJsonBudget(3, 65536, 7, 0)
KEY = "k3y-abcdef0123456789"
URL = "https://api.example.gov/v1/things?limit=2"


def page(rows, *, count, next_url=None):
    return json.dumps({"things": rows, "paging": {"count": count, "next": next_url}}).encode()


def response(body, status=200, *, content_type="application/json", **headers):
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


def reader(transport, **kwargs):
    return PagedJsonReader(family=FAMILY, budget=BUDGET, api_key=KEY, transport=transport, **kwargs)


def test_credential_travels_only_as_a_header_and_pages_carry_exact_bytes():
    first = page([{"id": 1}, {"id": 2}], count=3, next_url="https://api.example.gov/v1/things?limit=2&offset=2")
    second = page([{"id": 3}], count=3)
    transport = Transport(response(first), response(second))
    with reader(transport) as source:
        pages = list(source.pages(URL, records_key="things"))
    assert [p.page_index for p in pages] == [0, 1]
    assert pages[0].capture.body == first and pages[1].capture.body == second
    assert [len(p.records) for p in pages] == [2, 1]
    assert pages[0].declared_count == 3 and pages[1].next_url is None
    assert pages[0].records[0]["id"] == 1
    assert all(call.headers["x-api-key"] == KEY for call in transport.calls)
    assert all("api_key" not in str(call.url) for call in transport.calls)
    assert pages[0].sha256 == pages[0].capture.sha256


@pytest.mark.parametrize(
    "responses,message",
    [
        ((response(page([{"id": 1}], count=2)),), "declared and observed"),
        ((response(page([{"id": 1}, {"id": 2}, {"id": 3}], count=2)),), "more records than it declared"),
        ((response(page([{"id": 1}], count=2, next_url=URL)),), "repeated its continuation"),
        (
            (
                response(page([{"id": 1}], count=2, next_url="https://api.example.gov/v1/things?offset=1")),
                response(page([{"id": 2}], count=5)),
            ),
            "declared count changed",
        ),
        (
            (response(page([{"id": 1}], count=2, next_url="https://other.example.gov/v1/things")),),
            "HTTPS api.example.gov",
        ),
        ((response(page([{"id": 1}], count=2, next_url="https://api.example.gov/v1/things?api_key=x")),), "credential"),
        ((response(b'{"things": {}, "paging": {"count": 1}}'),), "omitted its things list"),
        ((response(b'{"things": [1], "paging": {"count": 1}}'),), "omitted its things list"),
        ((response(b'{"things": [], "paging": {"count": -1}}'),), "declared count is invalid"),
        ((response(b'{"things": [], "paging": {"count": true}}'),), "declared count is invalid"),
        ((response(b'{"things": [], "paging": {"count": 0, "next": ""}}'),), "continuation is invalid"),
        ((response(b'{"things": [], "things": []}'),), "repeats field"),
        ((response(b"[]"),), "not a JSON object"),
        ((response(b"<html>Checking your browser</html>", content_type="text/html"),), "Content-Type"),
        ((response(b"<html>Checking your browser</html>"),), "JSON"),
    ],
)
def test_page_shape_and_traversal_refusals(responses, message):
    transport = Transport(*responses)
    with reader(transport) as source, pytest.raises(PagedJsonSourceError, match=message) as raised:
        list(source.pages(URL, records_key="things"))
    assert raised.value.paged_json_acquisition["family"] == "example"


def test_page_bound_reached_before_terminal_page_refuses_rather_than_ending():
    transport = Transport(
        response(page([{"id": 1}], count=3, next_url="https://api.example.gov/v1/things?offset=1")),
        response(page([{"id": 2}], count=3, next_url="https://api.example.gov/v1/things?offset=2")),
    )
    with reader(transport) as source, pytest.raises(PagedJsonSourceError, match="page bound"):
        list(source.pages(URL, records_key="things", max_pages=2))
    assert len(transport.calls) == 2


def test_zero_count_is_an_observation_not_absence():
    transport = Transport(response(page([], count=0)))
    with reader(transport) as source:
        pages = list(source.pages(URL, records_key="things"))
    assert len(pages) == 1 and pages[0].records == () and pages[0].declared_count == 0


def test_credential_echo_is_refused_without_retaining_bytes():
    transport = Transport(response(page([{"token": KEY}], count=1)))
    with reader(transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.page(URL, records_key="things")
    assert not hasattr(raised.value, "refused_response")
    assert not hasattr(raised.value, "capture")


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_aborts(status):
    transport = Transport(httpx.Response(status, stream=httpx.ByteStream(b"")))
    with reader(transport) as source, pytest.raises(CredentialRefusedError):
        source.page(URL, records_key="things")


@pytest.mark.parametrize("status", [404, 410])
def test_unavailable_page_keeps_its_capture(status):
    transport = Transport(response(b"gone", status))
    with reader(transport) as source, pytest.raises(PagedJsonUnavailableError) as raised:
        source.page(URL, records_key="things")
    assert raised.value.capture.body == b"gone"


def test_retry_then_success_consumes_the_page_budget_and_exhaustion_is_not_absence():
    transport = Transport(response(page([], count=0), status=503), response(page([], count=0)))
    with reader(transport) as source:
        first = source.page(URL, records_key="things")
    assert first.declared_count == 0 and len(transport.calls) == 2
    transport = Transport(response(b"", 503), response(b"", 503), response(b"", 503))
    with reader(transport) as source, pytest.raises(Exception, match="retryable|budget"):
        source.page(URL, records_key="things")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.gov/v1/things",
        "https://api.example.gov",
        "https://api.example.gov/v1/things?api_key=x",
        "ftp://x",
        5,
    ],
)
def test_first_url_must_be_the_publisher_route_without_a_credential(url):
    transport = Transport()
    with reader(transport) as source, pytest.raises(PagedJsonSourceError):
        list(source.pages(url, records_key="things"))
    assert not transport.calls


def test_family_and_reader_configuration_is_explicit():
    with pytest.raises(ValueError):
        JsonPageFamily(name="", label="x", host="h", next_path=("n",), count_path=("c",))
    with pytest.raises(ValueError):
        JsonPageFamily(name="x", label="x", host="h", next_path=(), count_path=("c",))
    with pytest.raises(ValueError):
        PagedJsonReader(family=FAMILY, budget=BUDGET, api_key=None, transport=Transport())
    with pytest.raises(ValueError):
        PagedJsonReader(family=FAMILY, budget=BUDGET, api_key=" k ", transport=Transport())
    with pytest.raises(TypeError):
        PagedJsonReader(family="example", budget=BUDGET, api_key=KEY, transport=Transport())
    keyless = replace(FAMILY, requires_credential=False, credential_header=None)
    transport = Transport(response(page([], count=0)))
    with PagedJsonReader(family=keyless, budget=BUDGET, transport=transport) as source:
        source.page(URL, records_key="things")
    assert "x-api-key" not in transport.calls[0].headers
    for fields in ({"max_requests": 0}, {"max_page_bytes": 64 * 1024**2 + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            replace(BUDGET, **fields)
    with pytest.raises(ValueError):
        list(reader(Transport()).pages(URL, records_key="things", max_pages=0))


POST_FAMILY = JsonPageFamily(
    name="poster",
    label="Poster",
    host="api.example.gov",
    method="POST",
    next_kind="page-number",
    next_path=("meta", "next"),
    count_path=("meta", "total"),
    credential_header=None,
    requires_credential=False,
)
OFFSET_FAMILY = JsonPageFamily(
    name="walker",
    label="Walker",
    host="api.example.gov",
    next_kind="offset",
    credential_header="Authorization",
    credential_format="Token {key}",
    requires_credential=False,
)
PLACEHOLDER_FAMILY = replace(FAMILY, drop_query_names=frozenset({"api_key"}))


def post_page(rows, *, total, next_page):
    return json.dumps({"things": rows, "meta": {"total": total, "next": next_page}}).encode()


def test_post_page_number_walk_rewrites_the_body_and_records_it():
    transport = Transport(
        response(post_page([{"id": 1}, {"id": 2}], total=3, next_page=2)),
        response(post_page([{"id": 3}], total=3, next_page=None)),
    )
    with PagedJsonReader(family=POST_FAMILY, budget=BUDGET, transport=transport) as source:
        pages = list(
            source.pages("https://api.example.gov/v2/things/", records_key="things", body={"limit": 2, "page": 1})
        )
    assert [p.request_body["page"] for p in pages] == [1, 2] and pages[0].next_body == {"limit": 2, "page": 2}
    assert pages[0].capture.method == "POST" and pages[0].capture.request_body == b'{"limit":2,"page":1}'
    assert transport.calls[1].headers["content-type"] == "application/json"
    assert transport.calls[1].read() == b'{"limit":2,"page":2}'
    assert pages[1].next_url is None and pages[1].next_body is None


@pytest.mark.parametrize(
    "second,message",
    [
        (post_page([{"id": 3}], total=3, next_page=2), "does not advance"),
        (post_page([{"id": 3}], total=3, next_page=0), "page number is invalid"),
        (post_page([{"id": 3}], total=3, next_page="3"), "page number is invalid"),
    ],
)
def test_post_walk_refuses_a_continuation_that_does_not_advance(second, message):
    transport = Transport(response(post_page([{"id": 1}, {"id": 2}], total=3, next_page=2)), response(second))
    with (
        PagedJsonReader(family=POST_FAMILY, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match=message),
    ):
        list(source.pages("https://api.example.gov/v2/things/", records_key="things", body={"limit": 2, "page": 1}))


def test_post_pages_require_a_body_and_get_pages_forbid_one():
    with (
        PagedJsonReader(family=POST_FAMILY, budget=BUDGET, transport=Transport()) as source,
        pytest.raises(PagedJsonSourceError, match="require a request body"),
    ):
        source.page("https://api.example.gov/v2/things/", records_key="things")
    with reader(Transport()) as source, pytest.raises(PagedJsonSourceError, match="forbid a request body"):
        source.page(URL, records_key="things", body={"page": 1})


def test_post_body_carrying_the_credential_is_refused_before_any_request():
    keyed = replace(POST_FAMILY, credential_header="X-Api-Key", requires_credential=True)
    transport = Transport()
    with (
        PagedJsonReader(family=keyed, budget=BUDGET, api_key=KEY, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="must not carry the credential"),
    ):
        source.page("https://api.example.gov/v2/things/", records_key="things", body={"page": 1, "token": KEY})
    assert not transport.calls


def test_offset_walk_advances_by_rows_received_and_ends_at_a_short_page():
    def page_of(n):
        return json.dumps({"things": [{"id": i} for i in range(n)], "aggregations": {}}).encode()

    transport = Transport(response(page_of(2)), response(page_of(2)), response(page_of(1)))
    with PagedJsonReader(family=OFFSET_FAMILY, budget=BUDGET, api_key="tok", transport=transport) as source:
        pages = list(source.pages("https://api.example.gov/v1/things?limit=2&offset=0", records_key="things"))
    assert [len(p.records) for p in pages] == [2, 2, 1] and all(p.declared_count is None for p in pages)
    assert [str(c.url).rsplit("offset=", 1)[1] for c in transport.calls] == ["0", "2", "4"]
    assert transport.calls[0].headers["authorization"] == "Token tok"
    transport = Transport(response(page_of(3)))
    with (
        PagedJsonReader(family=OFFSET_FAMILY, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="more rows than its limit"),
    ):
        source.page("https://api.example.gov/v1/things?limit=2&offset=0", records_key="things")
    with (
        PagedJsonReader(family=OFFSET_FAMILY, budget=BUDGET, transport=Transport(response(page_of(1)))) as source,
        pytest.raises(PagedJsonSourceError, match="explicit positive limit"),
    ):
        source.page("https://api.example.gov/v1/things?offset=0", records_key="things")


def test_publisher_placeholder_credential_parameters_are_dropped_before_requesting():
    first = page([{"id": 1}], count=2, next_url="https://api.example.gov/v1/things?api_key=REPLACE_WITH_API_KEY&page=1")
    second = page([{"id": 2}], count=2)
    transport = Transport(response(first), response(second))
    with PagedJsonReader(family=PLACEHOLDER_FAMILY, budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.pages(URL, records_key="things"))
    assert pages[0].next_url == "https://api.example.gov/v1/things?page=1"
    assert "api_key" not in str(transport.calls[1].url) and transport.calls[1].headers["x-api-key"] == KEY


def test_family_contract_combinations_are_checked():
    with pytest.raises(ValueError, match="requires next_path"):
        JsonPageFamily(name="x", label="x", host="h", next_kind="page-number")
    with pytest.raises(ValueError, match="offset walk"):
        JsonPageFamily(name="x", label="x", host="h", next_kind="offset", next_path=("n",))
    with pytest.raises(ValueError, match="POST list"):
        JsonPageFamily(name="x", label="x", host="h", method="POST", next_path=("n",))
    with pytest.raises(ValueError, match="credential_format"):
        JsonPageFamily(name="x", label="x", host="h", next_path=("n",), credential_format="Token")


FLAG_FAMILY = JsonPageFamily(
    name="flagged",
    label="Flagged",
    host="api.example.gov",
    next_kind="page-number",
    next_path=("meta", "hasNextPage"),
    page_field="page[number]",
    count_path=("meta", "total"),
    count_kind="advisory",
    media_types=("application/json", "application/vnd.api+json"),
    credential_header=None,
    requires_credential=False,
)


def flag_page(rows, *, total, has_next):
    return json.dumps({"things": rows, "meta": {"total": total, "hasNextPage": has_next}}).encode()


def test_boolean_has_next_advances_the_page_field_and_advisory_counts_may_drift():
    first = flag_page([{"id": 1}, {"id": 2}], total=57380, has_next=True)
    second = flag_page([{"id": 3}], total=57383, has_next=False)
    transport = Transport(
        response(first, content_type="application/vnd.api+json;charset=utf-8"),
        response(second),
    )
    with PagedJsonReader(family=FLAG_FAMILY, budget=BUDGET, transport=transport) as source:
        pages = list(
            source.pages("https://api.example.gov/v4/things?page%5Bsize%5D=2&page%5Bnumber%5D=1", records_key="things")
        )
    assert [p.declared_count for p in pages] == [57380, 57383]
    assert pages[0].next_url.endswith("page%5Bnumber%5D=2") and pages[1].next_url is None
    assert str(transport.calls[1].url).endswith("page%5Bnumber%5D=2")


def test_has_next_flag_without_a_page_field_and_an_undeclared_media_type_refuse():
    transport = Transport(response(flag_page([{"id": 1}], total=1, has_next=True)))
    with (
        PagedJsonReader(family=FLAG_FAMILY, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="has-next flag needs"),
    ):
        source.page("https://api.example.gov/v4/things", records_key="things")
    transport = Transport(response(page([{"id": 1}], count=1), content_type="application/vnd.api+json"))
    with reader(transport) as source, pytest.raises(PagedJsonSourceError, match="Content-Type"):
        source.page(URL, records_key="things")


def test_keyless_readers_keep_a_refusal_body_and_keyed_readers_do_not():
    denied = b"<Error><Code>AccessDenied</Code></Error>"
    transport = Transport(
        httpx.Response(403, stream=httpx.ByteStream(denied), headers={"content-type": "application/xml"})
    )
    keyless = replace(FAMILY, credential_header=None, requires_credential=False)
    with (
        PagedJsonReader(family=keyless, budget=BUDGET, transport=transport) as source,
        pytest.raises(CredentialRefusedError) as raised,
    ):
        source.page(URL, records_key="things")
    assert raised.value.refused_response.response_bytes == denied
    assert raised.value.refused_response.unavailable_reason == "access-refused"
    transport = Transport(
        httpx.Response(403, stream=httpx.ByteStream(denied), headers={"content-type": "application/xml"})
    )
    with reader(transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.page(URL, records_key="things")
    assert raised.value.refused_response.response_bytes is None


def test_cookies_set_by_one_response_do_not_steer_the_next_request():
    first = httpx.Response(
        200,
        stream=httpx.ByteStream(page([{"id": 1}], count=2, next_url="https://api.example.gov/v1/things?offset=1")),
        headers={"content-type": "application/json", "set-cookie": "term=21; Path=/"},
    )
    transport = Transport(first, response(page([{"id": 2}], count=2)))
    with reader(transport) as source:
        list(source.pages(URL, records_key="things"))
    assert "cookie" not in transport.calls[1].headers


def test_family_reach_bounds_refuse_in_one_request_and_at_the_page_bound():
    bounded = replace(FLAG_FAMILY, max_reachable_records=100, limit_field="page[size]", window_hint="date window")
    transport = Transport(response(flag_page([{"id": 1}], total=101, has_next=True)))
    with (
        PagedJsonReader(family=bounded, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="reaches at most 98; narrow the date window") as raised,
    ):
        list(
            source.pages("https://api.example.gov/v4/things?page%5Bsize%5D=7&page%5Bnumber%5D=1", records_key="things")
        )
    assert raised.value.first_page.declared_count == 101 and len(transport.calls) == 1
    paged = replace(FLAG_FAMILY, max_page_number=1)
    transport = Transport(response(flag_page([{"id": 1}], total=5, has_next=True)))
    with (
        PagedJsonReader(family=paged, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="page\\[number\\] bound 1 reached"),
    ):
        list(source.pages("https://api.example.gov/v4/things?page%5Bnumber%5D=1", records_key="things"))
    assert len(transport.calls) == 1
    for fields in ({"max_reachable_records": 0}, {"max_page_number": True}):
        with pytest.raises(ValueError):
            replace(FLAG_FAMILY, **fields)
