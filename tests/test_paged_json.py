"""The shared paged-JSON reader: exact page capture, credential handling, traversal refusals and pooled walks.

Pins that a key travels only as a header and page bytes are kept verbatim, that
declared counts, continuations and content types are checked (empty success is
not absence), and the four walk kinds -- URL next, POST page number, offset and
boolean has-next -- with their bounds and refusals. The pooled-walk tests pin the
two settling rules (a clean walk alone, or a pool since the declared total last
changed), the restart on a total that moves mid-walk, the pass bound and the
known limit.
"""

import json
from dataclasses import replace
from datetime import date

import httpx
import pytest

from spicy_docs.reading.paged_json import (
    DeclaredCountChanged,
    DeclaredCountMismatch,
    IncompleteWalkError,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
    PagedJsonUnavailableError,
    WalkPass,
    pool_walks,
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
    """The key travels only as a header, page bytes are kept exactly, and page index, records and count follow."""
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


def test_a_single_object_under_the_records_key_reads_as_one_record_page():
    """A detail route's single object reads as a one-record page when the caller opts in with ``single_record``."""
    body = json.dumps({"things": {"id": 1, "name": "widget"}}).encode()
    transport = Transport(response(body))
    with reader(transport) as source:
        (result,) = list(source.pages(URL, records_key="things", single_record=True))
    assert result.records == ({"id": 1, "name": "widget"},)
    assert result.declared_count is None and result.next_url is None


def test_a_wrapper_object_without_single_record_still_refuses():
    """``single_record`` is opt-in: an object at ``records_key`` still refuses without it."""
    body = json.dumps({"things": {"id": 1, "name": "widget"}}).encode()
    transport = Transport(response(body))
    with (
        reader(transport) as source,
        pytest.raises(PagedJsonSourceError, match="omitted its things list"),
    ):
        source.page(URL, records_key="things")


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
        # An empty object still refuses -- empty success is not absence, and a detail route
        # answering {} carries no record to read (unlike the non-empty-object case above).
        ((response(b'{"things": {}, "paging": {"count": 1}}'),), "omitted its things list"),
        ((response(b'{"things": [1], "paging": {"count": 1}}'),), "omitted its things list"),
        ((response(b'{"things": "nope", "paging": {"count": 1}}'),), "omitted its things list"),
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
    """Count mismatches, repeated continuations, bad hosts or credentials, wrong types and non-objects all refuse."""
    transport = Transport(*responses)
    with reader(transport) as source, pytest.raises(PagedJsonSourceError, match=message) as raised:
        list(source.pages(URL, records_key="things"))
    assert raised.value.paged_json_acquisition["family"] == "example"


def test_a_traversal_refusals_context_carries_single_record_too():
    """A traversal-level refusal's context carries ``singleRecord`` and ``recordsKey`` like a page refusal's."""
    transport = Transport(response(page([{"id": 1}], count=2)))
    with (
        reader(transport) as source,
        pytest.raises(PagedJsonSourceError, match="declared and observed") as raised,
    ):
        list(source.pages(URL, records_key="things", single_record=True))
    context = raised.value.paged_json_acquisition
    assert context["operation"] == "traversal"
    assert context["singleRecord"] is True
    assert context["recordsKey"] == "things"


def test_an_empty_object_still_refuses_with_single_record_too():
    """An empty object at ``records_key`` refuses even with ``single_record``: empty success is not absence."""
    body = b'{"things": {}, "paging": {"count": 1}}'
    transport = Transport(response(body))
    with (
        reader(transport) as source,
        pytest.raises(PagedJsonSourceError, match="omitted its things list"),
    ):
        source.page(URL, records_key="things", single_record=True)


def test_page_bound_reached_before_terminal_page_refuses_rather_than_ending():
    """Reaching ``max_pages`` before a terminal page refuses rather than ending the walk."""
    transport = Transport(
        response(page([{"id": 1}], count=3, next_url="https://api.example.gov/v1/things?offset=1")),
        response(page([{"id": 2}], count=3, next_url="https://api.example.gov/v1/things?offset=2")),
    )
    with reader(transport) as source, pytest.raises(PagedJsonSourceError, match="page bound"):
        list(source.pages(URL, records_key="things", max_pages=2))
    assert len(transport.calls) == 2


def test_zero_count_is_an_observation_not_absence():
    """A declared count of zero yields one empty page, not absence."""
    transport = Transport(response(page([], count=0)))
    with reader(transport) as source:
        pages = list(source.pages(URL, records_key="things"))
    assert len(pages) == 1 and pages[0].records == () and pages[0].declared_count == 0


def test_credential_echo_is_refused_without_retaining_bytes():
    """A page echoing the credential refuses without retaining bytes or a capture."""
    transport = Transport(response(page([{"token": KEY}], count=1)))
    with reader(transport) as source, pytest.raises(CredentialRefusedError) as raised:
        source.page(URL, records_key="things")
    assert not hasattr(raised.value, "refused_response")
    assert not hasattr(raised.value, "capture")


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_aborts(status):
    """A 401 or 403 aborts as a credential refusal."""
    transport = Transport(httpx.Response(status, stream=httpx.ByteStream(b"")))
    with reader(transport) as source, pytest.raises(CredentialRefusedError):
        source.page(URL, records_key="things")


@pytest.mark.parametrize("status", [404, 410])
def test_unavailable_page_keeps_its_capture(status):
    """A 404 or 410 keeps its capture as unavailable evidence."""
    transport = Transport(response(b"gone", status))
    with reader(transport) as source, pytest.raises(PagedJsonUnavailableError) as raised:
        source.page(URL, records_key="things")
    assert raised.value.capture.body == b"gone"


def test_retry_then_success_consumes_the_page_budget_and_exhaustion_is_not_absence():
    """A 503 retries within budget and succeeds; exhaustion refuses rather than reading as absence."""
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
    """The first URL must be HTTPS on the family's host with no credential parameter; nothing is requested otherwise."""
    transport = Transport()
    with reader(transport) as source, pytest.raises(PagedJsonSourceError):
        list(source.pages(url, records_key="things"))
    assert not transport.calls


def test_family_and_reader_configuration_is_explicit():
    """Empty names or paths, missing or blank keys, wrong types and out-of-range budgets are all rejected."""
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
    """A POST page-number walk rewrites the body per page and records the exact method and body bytes."""
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
    """A POST continuation that repeats or invalidates its page number refuses."""
    transport = Transport(response(post_page([{"id": 1}, {"id": 2}], total=3, next_page=2)), response(second))
    with (
        PagedJsonReader(family=POST_FAMILY, budget=BUDGET, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match=message),
    ):
        list(source.pages("https://api.example.gov/v2/things/", records_key="things", body={"limit": 2, "page": 1}))


def test_post_pages_require_a_body_and_get_pages_forbid_one():
    """POST families require a request body and GET families forbid one."""
    with (
        PagedJsonReader(family=POST_FAMILY, budget=BUDGET, transport=Transport()) as source,
        pytest.raises(PagedJsonSourceError, match="require a request body"),
    ):
        source.page("https://api.example.gov/v2/things/", records_key="things")
    with reader(Transport()) as source, pytest.raises(PagedJsonSourceError, match="forbid a request body"):
        source.page(URL, records_key="things", body={"page": 1})


def test_post_body_carrying_the_credential_is_refused_before_any_request():
    """A POST body carrying the credential refuses before any request is made."""
    keyed = replace(POST_FAMILY, credential_header="X-Api-Key", requires_credential=True)
    transport = Transport()
    with (
        PagedJsonReader(family=keyed, budget=BUDGET, api_key=KEY, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="must not carry the credential"),
    ):
        source.page("https://api.example.gov/v2/things/", records_key="things", body={"page": 1, "token": KEY})
    assert not transport.calls


def test_offset_walk_advances_by_rows_received_and_ends_at_a_short_page():
    """The offset walk advances by rows received, ends at a short page, and refuses a page over or without a limit."""

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
    """Publisher placeholder credential parameters are dropped from continuations and replaced by the header."""
    first = page([{"id": 1}], count=2, next_url="https://api.example.gov/v1/things?api_key=REPLACE_WITH_API_KEY&page=1")
    second = page([{"id": 2}], count=2)
    transport = Transport(response(first), response(second))
    with PagedJsonReader(family=PLACEHOLDER_FAMILY, budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.pages(URL, records_key="things"))
    assert pages[0].next_url == "https://api.example.gov/v1/things?page=1"
    assert "api_key" not in str(transport.calls[1].url) and transport.calls[1].headers["x-api-key"] == KEY


def test_family_contract_combinations_are_checked():
    """Family contracts: next_kind needs next_path, offset takes none, POST needs a list,
    credential_format needs a header.
    """
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
    """A boolean has-next advances the page field while advisory counts may drift between pages."""
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
    """A has-next flag without a page field refuses, as does an undeclared media type."""
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
    """A keyless 403 keeps the refusal body and access-refused reason; a keyed one retains no bytes."""
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
    """A cookie set by one response is not sent on the next request."""
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
    """Reach and page-number bounds refuse on the first request, naming the bound and window hint; bad bounds too."""
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


def test_tuple_records_key_reaches_rows_nested_in_a_wrapper_object():
    """A tuple ``records_key`` reaches rows nested in a wrapper object, matching ``count_path``/``next_path``."""
    body = json.dumps({"wrapper": {"things": [{"id": 1}, {"id": 2}]}, "paging": {"count": 2, "next": None}}).encode()
    transport = Transport(response(body))
    with reader(transport) as source:
        result = source.page(URL, records_key=("wrapper", "things"))
    assert result.records_key == ("wrapper", "things")
    assert [row["id"] for row in result.records] == [1, 2]
    assert result.declared_count == 2


def test_tuple_records_key_miss_refuses_with_a_dotted_label():
    """A tuple key miss refuses with the dotted label ``wrapper.things``."""
    body = json.dumps({"wrapper": {}, "paging": {"count": 0, "next": None}}).encode()
    transport = Transport(response(body))
    with (
        reader(transport) as source,
        pytest.raises(PagedJsonSourceError, match="omitted its wrapper.things list"),
    ):
        source.page(URL, records_key=("wrapper", "things"))


def test_a_records_key_naming_one_object_reads_as_a_single_record_page():
    """With ``single_record``, a ``records_key`` naming one object reads as a one-record page with no count or next."""
    body = json.dumps({"thing": {"id": 1, "nested": {"more": True}}}).encode()
    transport = Transport(response(body))
    with reader(transport) as source:
        result = source.page(URL, records_key="thing", single_record=True)
    assert result.records == ({"id": 1, "nested": {"more": True}},)
    assert result.declared_count is None
    assert result.next_url is None


def test_a_tuple_records_key_naming_one_object_also_reads_as_a_single_record_page():
    """A tuple key naming one object also reads as a single-record page."""
    body = json.dumps({"wrapper": {"thing": {"id": 1}}}).encode()
    transport = Transport(response(body))
    with reader(transport) as source:
        result = source.page(URL, records_key=("wrapper", "thing"), single_record=True)
    assert result.records == ({"id": 1},)


def test_the_committee_bills_wrapper_key_refuses_without_single_record():
    """Reading the committee-bills wrapper as a string refuses without ``single_record``, not as a bogus record."""
    body = json.dumps(
        {"committee-bills": {"bills": [{"congress": 110}], "count": 1, "url": "https://api.example.gov/x"}}
    ).encode()
    transport = Transport(response(body))
    with (
        reader(transport) as source,
        pytest.raises(PagedJsonSourceError, match="omitted its committee-bills list"),
    ):
        source.page(URL, records_key="committee-bills")


# --- the whole-walk count checks ------------------------------------------------

NEXT = "https://api.example.gov/v1/things?limit=2&offset=2"


def test_a_terminal_count_disagreement_is_typed_and_carries_both_numbers():
    """The whole-walk count check raises ``DeclaredCountMismatch`` with the numbers, message unchanged.

    Ported from spicy-regs' ``test_congress_walk``, whose host reads past a
    bounded over-declaration (``committee/119`` declared 238 and served 236) by
    matching this message's text; the attributes replace that match.
    """
    transport = Transport(
        response(page([{"id": 1}, {"id": 2}], count=6, next_url=NEXT)), response(page([{"id": 3}, {"id": 4}], count=6))
    )
    with reader(transport) as source, pytest.raises(DeclaredCountMismatch) as raised:
        list(source.pages(URL, records_key="things"))
    error = raised.value
    assert isinstance(error, PagedJsonSourceError), "callers catching the base class still catch it"
    assert (error.declared, error.observed) == (6, 4)
    assert str(error) == "Example declared and observed record counts differ"
    context = error.paged_json_acquisition
    assert (context["operation"], context["declaredCount"], context["observedCount"]) == ("traversal", 6, 4)


def test_a_declared_count_that_moves_mid_walk_is_typed_and_carries_both_totals():
    transport = Transport(response(page([{"id": 1}], count=2, next_url=NEXT)), response(page([{"id": 2}], count=5)))
    with reader(transport) as source, pytest.raises(DeclaredCountChanged) as raised:
        list(source.pages(URL, records_key="things"))
    error = raised.value
    assert (error.declared, error.changed_to) == (2, 5)
    assert str(error) == "Example declared count changed during the traversal"
    assert error.paged_json_acquisition["operation"] == "traversal"


@pytest.mark.parametrize(
    "responses,max_pages",
    [
        pytest.param((response(page([{"id": 1}, {"id": 2}, {"id": 3}], count=2)),), 5, id="more-than-declared"),
        pytest.param((response(page([{"id": 1}], count=2, next_url=URL)),), 5, id="repeated-continuation"),
        pytest.param(
            (response(page([{"id": 1}], count=2, next_url=NEXT)), response(page([{"id": 2}], count=5))),
            5,
            id="count-changed",
        ),
        pytest.param((response(page([{"id": 1}], count=3, next_url=NEXT)),), 1, id="page-bound"),
    ],
)
def test_every_other_traversal_refusal_is_not_a_terminal_count_mismatch(responses, max_pages):
    """Only a terminal disagreement is a mismatch: a walk cut short or inconsistent is never read past as one."""
    transport = Transport(*responses)
    with reader(transport) as source, pytest.raises(PagedJsonSourceError) as raised:
        list(source.pages(URL, records_key="things", max_pages=max_pages))
    assert not isinstance(raised.value, DeclaredCountMismatch)


# --- pooled walks -----------------------------------------------------------------


class Walks:
    """Serves passes in order as ``pool_walks``' ``walk``, recording each pass asked for.

    A pass is ``(records, declared)``, a bare record value standing for
    ``{"id": value}``, or a ``DeclaredCountChanged`` the pass raises mid-walk.
    """

    def __init__(self, *passes):
        self.passes = passes
        self.asked = []

    def __call__(self, index):
        self.asked.append(index)
        walked = self.passes[index]
        if isinstance(walked, DeclaredCountChanged):
            raise walked
        records, declared = walked
        return WalkPass(tuple(r if isinstance(r, dict) else {"id": r} for r in records), declared)


def moved(declared, changed_to):
    return DeclaredCountChanged(
        "Example declared count changed during the traversal", declared=declared, changed_to=changed_to
    )


def pooled(walks, **kwargs):
    kwargs.setdefault("key", lambda record: record["id"])
    return pool_walks(walks, label="Example", **kwargs)


def ids(result):
    return [record["id"] for record in result.records]


def test_a_clean_walk_stands_alone():
    """No repeated identity and a distinct count equal to the declared total: nothing was skipped, one pass."""
    walks = Walks(([1, 2], 2), ([2, 1], 2))
    result = pooled(walks)
    assert (ids(result), result.declared, result.passes) == ([1, 2], 2, 1)
    assert walks.asked == [0]


def test_a_walk_that_repeats_one_record_and_skips_another_settles_on_the_next_clean_walk():
    """Every pass serves the declared row count; only identities show the skip, and the newest version wins.

    Ported from spicy-regs' amendments test: pass 1 repeats #2 and skips #3;
    pass 2 is clean, and the version pass 1 saw of #2 is older.
    """
    walks = Walks(
        ([1, {"id": 2, "updateDate": "2026-01-01"}, {"id": 2, "updateDate": "2026-01-01"}], 3),
        ([3, {"id": 2, "updateDate": "2026-02-01"}, 1], 3),
    )
    result = pooled(walks, version=lambda record: record.get("updateDate", ""))
    assert (sorted(ids(result)), result.passes) == ([1, 2, 3], 2)
    assert {r["id"]: r.get("updateDate") for r in result.records}[2] == "2026-02-01", "the newest version is kept"


def test_walks_that_are_never_clean_settle_when_their_pool_reaches_the_declared_total():
    walks = Walks(([1, 2, 2], 3), ([3, 3, 1], 3))
    result = pooled(walks)
    assert (sorted(ids(result)), result.passes) == ([1, 2, 3], 2)


def test_a_record_both_same_direction_passes_skip_is_pooled_from_the_opposite_pass():
    """Desc passes 1 and 3 put page boundaries on the same records and both skip C; asc pass 2 saw it.

    Counting only identities two passes saw would never count C, and refused this
    query at every pass bound the churn allowed.
    """
    walks = Walks((["A", "A", "G", "G"], 4), (["G", "C", "A", "A"], 4), (["A", "F", "G", "G"], 4))
    result = pooled(walks)
    assert (sorted(ids(result)), result.passes) == (["A", "C", "F", "G"], 3)


def _versions_of_one(version):
    """Record 1 is observed twice, in two passes, before record 2 completes the pool."""
    walks = Walks(
        ([{"id": 1, "v": "b", "n": 1}, {"id": 1, "v": "b", "n": 1}], 2),
        ([{"id": 1, "v": "a", "n": 2}, {"id": 1, "v": "a", "n": 2}], 2),
        ([{"id": 2, "v": "a"}, {"id": 2, "v": "a"}], 2),
    )
    return {record["id"]: record for record in pooled(walks, version=version).records}[1]["n"]


def test_without_a_version_the_latest_observation_wins_and_a_tied_version_goes_to_the_later():
    assert _versions_of_one(None) == 2
    assert _versions_of_one(lambda record: record["v"]) == 1, "the greater version is kept"
    assert _versions_of_one(lambda record: "same") == 2, "a tie goes to the later observation"


@pytest.mark.parametrize(
    "version,message",
    [
        (lambda record: None, "Example served a record with no version"),
        (lambda record: record["missing"], "Example could not read a record's version"),
        (lambda record: record["v"], "Example served versions that do not compare"),
    ],
)
def test_a_version_that_is_missing_or_does_not_compare_refuses(version, message):
    walks = Walks(([{"id": 1, "v": "2026-01-01"}, {"id": 1, "v": 20260101}], 2))
    with pytest.raises(PagedJsonSourceError, match=message):
        pooled(walks, version=version)


def test_a_version_that_does_not_parse_refuses():
    """A ``fromisoformat`` version raises ``ValueError`` on a malformed stamp; the walk refuses naming its label."""
    walks = Walks(([{"id": 1, "v": "last Tuesday"}], 1))
    with pytest.raises(PagedJsonSourceError, match="Example could not read a record's version"):
        pooled(walks, version=lambda record: date.fromisoformat(record["v"]))


def test_a_record_that_changes_between_passes_stays_one_identity_under_a_key():
    """Keyed by id, a proceeding whose filing count moves is one record; keyed by its whole JSON it never settles.

    spicy-regs keyed FCC ECFS proceedings by their whole document; the pool then
    grows by one identity per changed proceeding per pass.
    """

    def churning():
        return Walks(
            ([{"id": 1, "filings": 1}, {"id": 1, "filings": 1}, {"id": 3}], 3),
            ([{"id": 2}, {"id": 1, "filings": 2}, {"id": 1, "filings": 2}], 3),
            ([{"id": 3}, {"id": 3}, {"id": 1, "filings": 3}], 3),
            ([{"id": 2}, {"id": 2}, {"id": 1, "filings": 4}], 3),
        )

    result = pooled(churning())
    assert (sorted(ids(result)), result.passes) == ([1, 2, 3], 2)
    assert {r["id"]: r for r in result.records}[1]["filings"] == 2
    with pytest.raises(IncompleteWalkError, match="pooled 6 records, more than the 3 declared"):
        pooled(churning(), key=lambda record: json.dumps(record, sort_keys=True))


def test_a_deletion_that_lowers_the_total_starts_a_new_pool():
    """X is deleted after pass 1, whose pool would otherwise fill the slot of B, which passes 1 and 2 skip."""
    walks = Walks((["X", "A", "A"], 3), (["A", "A"], 2), (["B", "A"], 2))
    result = pooled(walks)
    assert (ids(result), result.passes) == (["B", "A"], 3)


def test_a_clean_walk_drops_what_earlier_walks_saw_and_it_did_not():
    """X is replaced by Z at an unchanged total, so the pool overfills; a clean walk is the whole list."""
    walks = Walks((["X", "A", "A"], 3), (["Z", "B", "B"], 3), (["A", "B", "Z"], 3))
    result = pooled(walks)
    assert (ids(result), result.passes) == (["A", "B", "Z"], 3)


def test_a_replacement_nothing_skips_overfills_the_pool_and_refuses():
    """X is replaced by Z at an unchanged total and no walk is clean, so the pool holds 4 against 3.

    Passes 3 and 4 have 3 distinct identities but repeat one, so neither is clean
    on its own (a count-less family can serve more rows than its total).
    """
    walks = Walks((["X", "A", "A"], 3), (["Z", "B", "B"], 3), (["A", "B", "Z", "Z"], 3), (["Z", "Z", "A", "B"], 3))
    message = (
        "pooled 4 records, more than the 3 declared, after 4 passes; records were replaced under an unchanged total"
    )
    with pytest.raises(IncompleteWalkError, match=message) as raised:
        pooled(walks)
    assert (raised.value.distinct, raised.value.declared) == (4, 3)


def test_known_limit_a_deletion_offset_by_an_insertion_that_later_walks_skip_settles_wrong():
    """Pinned so a fix is noticed: X is deleted and Z inserted between passes, and pass 2 skips Z.

    The total stays 3, so the pool keeps pass 1's X; ``{X, A, B}`` matches the
    total and the walk settles with X and without Z. No comparison of identity
    sets against a count sees it.
    """
    walks = Walks((["X", "A", "A"], 3), (["B", "A", "A"], 3))
    assert sorted(ids(pooled(walks))) == ["A", "B", "X"]


def test_a_pass_whose_total_moves_mid_walk_is_spent_and_pooling_restarts():
    """Growth then quiet: pass 1 sees the total move from 3 to 4, then two dirty passes pool to 4."""
    walks = Walks(moved(3, 4), (["D", "A", "A", "B"], 4), (["C", "C", "D", "A"], 4))
    result = pooled(walks)
    assert (sorted(ids(result)), result.declared, result.passes) == (["A", "B", "C", "D"], 4, 3)


def test_a_total_that_moves_mid_walk_discards_the_pool_even_when_it_moves_back():
    """During pass 2, Z is inserted (3 to 4) and then X deleted (back to 3); pass 3 skips Z.

    Pass 1's X must not carry into pass 3's pool, where it would fill Z's slot at
    the same total; pass 4 is clean.
    """
    walks = Walks((["X", "A", "A"], 3), moved(3, 4), (["B", "A", "A"], 3), (["Z", "A", "B"], 3))
    result = pooled(walks)
    assert (ids(result), result.passes) == (["Z", "A", "B"], 4)


@pytest.mark.parametrize(
    "passes,restarted",
    [
        pytest.param([moved(3, 4), moved(4, 5), moved(5, 6), moved(6, 7)], 4, id="moves-mid-walk"),
        pytest.param(
            [
                (["A", "A", "B"], 4),
                (["C", "C", "D", "E"], 5),
                (["F", "F", "A", "B", "C"], 6),
                (["G", "G", "A", "B", "C", "D"], 7),
            ],
            0,
            id="grows-between",
        ),
    ],
)
def test_continuous_growth_refuses_after_its_passes(passes, restarted):
    walks = Walks(*passes)
    with pytest.raises(IncompleteWalkError) as raised:
        pooled(walks)
    error = raised.value
    assert (error.declared, error.passes, error.restarted) == (7, 4, restarted)
    assert walks.asked == [0, 1, 2, 3]


def test_a_query_still_short_after_its_bounded_passes_refuses_naming_the_numbers():
    """Ported from spicy-regs' amendments refusal: every pass repeats #1, so the pool never reaches 2."""
    walks = Walks(*[([1, 1], 2)] * 4)
    with pytest.raises(IncompleteWalkError, match="Example: pooled 1 of 2 declared records after 4 passes") as raised:
        pooled(walks)
    assert walks.asked == [0, 1, 2, 3], "the default bound is four walks"
    assert (raised.value.declared, raised.value.distinct, raised.value.passes) == (2, 1, 4)
    assert isinstance(raised.value, PagedJsonSourceError)


def test_an_empty_query_is_a_clean_walk():
    """A declared zero with nothing served is an observation, not absence, and settles like any clean walk."""
    result = pooled(Walks(([], 0)))
    assert (result.records, result.declared, result.passes) == ((), 0, 1)


@pytest.mark.parametrize("identity", [None, "", "  ", True, 1.5, {"id": 1}, (), ("119", ""), ("119", None)])
def test_a_record_without_a_usable_identity_key_refuses(identity):
    """A missing identity would collapse every such record into one; a record is never its own key."""
    with pytest.raises(PagedJsonSourceError, match="Example served a record without a usable identity key"):
        pooled(Walks(([{"id": identity}], 1)))


def test_identity_keys_may_be_strings_integers_or_tuples_of_them():
    walks = Walks(([{"id": ("119", "samdt", 3)}, {"id": 7}], 2))
    assert ids(pooled(walks)) == [("119", "samdt", 3), 7]


@pytest.mark.parametrize("max_passes", [0, -1, True, "3"])
def test_a_pass_bound_must_be_a_positive_integer(max_passes):
    with pytest.raises(ValueError, match="positive integer"):
        pooled(Walks(), max_passes=max_passes)


def test_a_walk_pass_needs_a_declared_total():
    with pytest.raises(ValueError, match="non-negative"):
        WalkPass((), -1)
    with pytest.raises(PagedJsonSourceError, match="Example pooled walk needs a declared total"):
        WalkPass.from_pages([], label="Example")


def test_a_walk_pass_refuses_a_total_an_advisory_family_let_drift():
    """``pages()`` checks a constant total only for exact-count families; ``from_pages`` checks it for every family."""
    transport = Transport(response(page([{"id": 1}], count=3, next_url=NEXT)), response(page([{"id": 2}], count=4)))
    advisory = PagedJsonReader(
        family=replace(FAMILY, count_kind="advisory"), budget=BUDGET, api_key=KEY, transport=transport
    )
    with advisory as source, pytest.raises(DeclaredCountChanged) as raised:
        WalkPass.from_pages(source.pages(URL, records_key="things"), label="Example")
    assert (raised.value.declared, raised.value.changed_to) == (3, 4)
    assert str(raised.value) == "Example declared count changed during the traversal"


def test_a_walk_pass_reads_a_readers_pages():
    """``from_pages`` consumes one walk: every page's records, in order, and the declared total they state."""
    transport = Transport(
        response(page([{"id": 1}, {"id": 2}], count=3, next_url=NEXT)), response(page([{"id": 3}], count=3))
    )
    with reader(transport) as source:
        walked = WalkPass.from_pages(source.pages(URL, records_key="things"), label="Example")
    assert (walked.records, walked.declared) == (({"id": 1}, {"id": 2}, {"id": 3}), 3)
