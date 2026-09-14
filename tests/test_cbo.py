"""CBO's per-Congress feed is read as an observation whose Links name publications.

The feed is CBO's own ``<response>``/``<item key="N">`` XML, not RSS 2.0, and it
carries no topic, budget-function, mandate or PAYGO field. ``/cost-estimates/xml``
and every PDF path answer a DataDome bot challenge, which this family names as a
challenge rather than as a credential refusal, because it holds no credential.

There is no PDF fixture: no CBO estimate PDF is reachable keyless, so the PDF
bytes below are built here and are not the publisher's. See
`tests/fixtures/cbo/README.md`.
"""

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.cbo import (
    CBO_COST_ESTIMATES_FEED_URL,
    CboAcquirer,
    CboBudget,
    CboChallengeError,
    CboSourceError,
    CboUnavailableError,
    cbo_cost_estimates_feed_locator,
    cbo_estimate_document_locator,
    cbo_per_congress_feed_locator,
    parse_cbo_cost_estimates_feed,
)
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "cbo"
FEED = (FIXTURES / "cbo-119congress-cost-estimates.xml").read_bytes()
CHALLENGE = (FIXTURES / "cbo-datadome-challenge.html").read_bytes()
BUDGET = CboBudget(3, 4 * 1024 * 1024, 7, 0)
FEED_119_URL = "https://www.cbo.gov/rss/119congress-cost-estimates.xml"
PDF_URL = "https://www.cbo.gov/system/files/2020-07/HR1957directspending.pdf"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
MINIMAL = (
    b'<?xml version="1.0"?>\n<response><item key="0"><Title>A</Title>'
    b"<Date>Fri, 11 Sep 2026 17:00:00 -0400</Date>"
    b"<Link>https://www.cbo.gov/publication/62589</Link>"
    b"<Description>D</Description><Bill_Number>S. 1</Bill_Number></item></response>"
)


def response(body=FEED, status=200, *, content_type="text/xml; charset=UTF-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


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


# --- the feed CBO actually serves -------------------------------------------------


def test_pinned_feed_yields_publications_in_feed_order_with_publisher_spellings():
    feed = parse_cbo_cost_estimates_feed(FEED)
    assert [item.index for item in feed.items] == [0, 1]
    first, second = feed.items
    assert first.publication_id == "62589" and first.link == "https://www.cbo.gov/publication/62589"
    assert first.title.startswith("Legislation considered under suspension of the Rules")
    assert first.date == "Fri, 11 Sep 2026 17:00:00 -0400"
    assert first.bill_number is None, "a procedural item publishes an empty Bill_Number; that is a value"
    assert second.publication_id == "62720" and second.bill_number == "S. 4429"
    assert second.title == "S. 4429, Connected Vehicle Security Act of 2026"
    assert second.description == (
        "As ordered reported by the Senate Committee on Commerce, Science, and Transportation \non July 22, 2026"
    ), "surrounding whitespace is trimmed; CBO's interior line break is kept verbatim"


def test_feed_carries_no_channel_header_and_no_fiscal_facets():
    feed = parse_cbo_cost_estimates_feed(FEED)
    assert not hasattr(feed, "title") and not hasattr(feed, "last_build_date")
    assert not any(hasattr(item, name) for item in feed.items for name in ("topics", "budget_functions", "paygo"))


def test_empty_response_is_a_requested_empty_observation_not_a_refusal():
    assert parse_cbo_cost_estimates_feed(b'<?xml version="1.0"?><response></response>').items == ()


def test_numeric_character_references_resolve_to_the_publishers_text():
    body = MINIMAL.replace(b"<Title>A</Title>", b"<Title>Division N&#x2014;Relief Act</Title>")
    assert parse_cbo_cost_estimates_feed(body).items[0].title == "Division N—Relief Act"


@pytest.mark.parametrize(
    "body,message",
    [
        (MINIMAL.replace(b"<response>", b"<rss>").replace(b"</response>", b"</rss>"), "root element is not"),
        (MINIMAL.replace(b'<item key="0">', b'<entry key="0">').replace(b"</item>", b"</entry>"), "not <item>"),
        (MINIMAL.replace(b'key="0"', b'key="1"'), "position in document order"),
        (MINIMAL.replace(b'key="0"', b'key="0" mode="x"'), "exactly a key attribute"),
        (MINIMAL.replace(b'<item key="0">', b"<item>"), "exactly a key attribute"),
        (MINIMAL.replace(b"<Title>A</Title>", b""), "nonempty Title"),
        (MINIMAL.replace(b"<Title>A</Title>", b"<Title> </Title>"), "nonempty Title"),
        (MINIMAL.replace(b"<Date>", b"<Dates>").replace(b"</Date>", b"</Dates>"), "unknown field Dates"),
        (MINIMAL.replace(b"<Description>D</Description>", b"<cbo:topic>Health</cbo:topic>"), "malformed"),
        (
            MINIMAL.replace(
                b"<Description>D</Description>",
                b'<topic xmlns="https://www.cbo.gov/xmlns/cost-estimates/1.0">Health</topic>',
            ),
            "unknown field",
        ),
        (MINIMAL.replace(b"<Title>A</Title>", b"<Title>A</Title><Title>B</Title>"), "repeats Title"),
        (MINIMAL.replace(b"<Title>A</Title>", b"<Title><b>A</b></Title>"), "nests an item field"),
        (MINIMAL.replace(b"publication/62589", b"publications/62589"), "not a canonical publication URL"),
        (MINIMAL.replace(b"https://www.cbo.gov/publication", b"http://www.cbo.gov/publication"), "not a canonical"),
        (MINIMAL.replace(b"publication/62589", b"publication/62589/"), "does not name a publication"),
        (MINIMAL.replace(b"publication/62589", b"publication/062589"), "does not name a publication"),
        (
            MINIMAL.replace(
                b"</item></response>",
                b"</item>" + MINIMAL[MINIMAL.index(b"<item") :].replace(b'key="0"', b'key="1"'),
            ),
            "more than once",
        ),
        (b'<!DOCTYPE response [<!ENTITY x "y">]>' + MINIMAL, "DOCTYPE"),
        (MINIMAL[:-11], "malformed"),
        (CHALLENGE, "root element is not"),
        (b"<html><body>Please enable JS</body></html>", "root element is not"),
        (b"", "nonempty"),
    ],
)
def test_feed_refusals_name_the_failed_check(body, message):
    with pytest.raises(CboSourceError, match=message):
        parse_cbo_cost_estimates_feed(body)


@pytest.mark.parametrize("max_bytes", [0, True, 64 * 1024**2 + 1])
def test_feed_bounds_are_explicit(max_bytes):
    with pytest.raises(CboSourceError, match="max_bytes"):
        parse_cbo_cost_estimates_feed(MINIMAL, max_bytes=max_bytes)
    with pytest.raises(CboSourceError):
        parse_cbo_cost_estimates_feed(MINIMAL, max_bytes=len(MINIMAL) - 1)


# --- qualification against every real feed retained -------------------------------

RECEIPTS = Path.home() / "Work/corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14"
REFSPEC = Path.home() / "Work/RefSpec/tests/fixtures/cbo_topic_codes"
RETAINED = [
    (RECEIPTS / "09-116congress.body", 1259),
    (RECEIPTS / "06-117congress.body", 1191),
    (RECEIPTS / "06-118congress.body", 1533),
    (RECEIPTS / "02-119congress.body", 1192),
    (REFSPEC / "cbo-119congress-cost-estimates-2026-08-04.xml", 1058),
]


@pytest.mark.parametrize("path,items", RETAINED, ids=lambda value: getattr(value, "stem", value))
def test_parser_qualifies_against_every_retained_real_feed(path, items):
    """Receipts live outside the repository; skip rather than fail when they are absent."""
    if not path.exists():
        pytest.skip(f"retained capture not present: {path}")
    feed = parse_cbo_cost_estimates_feed(path.read_bytes())
    assert len(feed.items) == items
    assert [item.index for item in feed.items] == list(range(items))
    assert len({item.publication_id for item in feed.items}) == items
    assert all(item.title and item.date and item.link for item in feed.items)


# --- locators ---------------------------------------------------------------------


def test_locators_are_the_publishers_own_spellings():
    assert cbo_cost_estimates_feed_locator() == CBO_COST_ESTIMATES_FEED_URL
    assert cbo_per_congress_feed_locator(119) == FEED_119_URL
    assert cbo_estimate_document_locator(PDF_URL) == PDF_URL


@pytest.mark.parametrize("congress", [0, 1000, True, "119", 119.0, None])
def test_per_congress_locator_refuses_anything_but_a_congress_number(congress):
    with pytest.raises(CboSourceError, match="congress must be"):
        cbo_per_congress_feed_locator(congress)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.cbo.gov/system/files/a.pdf",
        "https://cbo.gov/system/files/a.pdf",
        "https://www.cbo.gov:8443/system/files/a.pdf",
        "https://evil.example/system/files/a.pdf",
        "https://www.cbo.gov/system/files/a.pdf?token=1",
        "https://www.cbo.gov/system/files/a.pdf#page=2",
        "https://www.cbo.gov/publication/62720",
        "https://www.cbo.gov/system/files/../a.pdf",
        b"https://www.cbo.gov/a.pdf",
    ],
)
def test_document_locator_refuses_anything_but_an_official_cbo_pdf(url):
    with pytest.raises(CboSourceError, match="estimate document must be"):
        cbo_estimate_document_locator(url)


# --- acquisition ------------------------------------------------------------------


def test_acquirer_captures_exact_feed_bytes_keyless():
    transport = Transport(response())
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_per_congress_feed(119)
    assert result.capture.body == FEED and result.capture.requested_url == FEED_119_URL
    assert len(result.feed.items) == 2 and result.request_count == 1 and result.budget == BUDGET
    assert "x-api-key" not in transport.calls[0].headers
    assert "authorization" not in transport.calls[0].headers
    assert transport.calls[0].headers["accept-encoding"] == "identity"


def test_a_call_may_narrow_the_byte_allowance_but_never_raise_it():
    with CboAcquirer(budget=BUDGET, transport=Transport(response())) as source, pytest.raises(CboSourceError):
        source.acquire_per_congress_feed(119, max_bytes=len(FEED) - 1)


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(CHALLENGE, 403, content_type="text/html;charset=utf-8"), CboChallengeError, "bot challenge"),
        (response(CHALLENGE, content_type="text/html;charset=utf-8"), CboSourceError, "Content-Type differs"),
        (response(CHALLENGE), CboSourceError, "root element is not"),
        (response(b"not found", 404, content_type="text/html; charset=UTF-8"), CboUnavailableError, "HTTP 404"),
        (response(b"", 410), CboUnavailableError, "HTTP 410"),
    ],
)
def test_wrong_shape_or_walled_feed_never_succeeds(answer, error, message):
    transport = Transport(answer)
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire_per_congress_feed(119)
    assert raised.value.cbo_acquisition["operation"] == "per-congress-feed"
    assert len(transport.calls) == 1


def test_a_200_that_is_not_the_expected_shape_retains_its_bytes():
    transport = Transport(response(b'<?xml version="1.0"?><response><item key="9"/></response>'))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboSourceError) as raised:
        source.acquire_per_congress_feed(119)
    assert raised.value.refused_response.response_bytes == b'<?xml version="1.0"?><response><item key="9"/></response>'


def test_the_walled_cost_estimates_route_is_recorded_as_a_challenge_not_a_credential_refusal():
    transport = Transport(response(CHALLENGE, 403, content_type="text/html;charset=utf-8"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboChallengeError) as raised:
        source.acquire_cost_estimates_feed()
    assert raised.value.url == CBO_COST_ESTIMATES_FEED_URL
    assert raised.value.cbo_acquisition["operation"] == "cost-estimates-feed"
    assert str(transport.calls[0].url) == CBO_COST_ESTIMATES_FEED_URL


def test_the_cost_estimates_route_would_be_read_by_the_same_parser_if_it_ever_answered():
    transport = Transport(response(MINIMAL))
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_cost_estimates_feed()
    assert result.capture.body == MINIMAL and result.feed.items[0].publication_id == "62589"


# --- the estimate document --------------------------------------------------------


def test_estimate_document_identity_is_proved_by_media_type_magic_and_final_url():
    transport = Transport(response(PDF, content_type="application/pdf"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_estimate_document(PDF_URL)
    assert result.capture.body == PDF and result.capture.requested_url == PDF_URL
    assert result.capture.byte_size == len(PDF) and result.request_count == 1


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (
            response(b"<!doctype html><html>Estimate</html>", content_type="application/pdf"),
            CboSourceError,
            "PDF- magic",
        ),
        (response(b"PK\x03\x04not a pdf", content_type="application/pdf"), CboSourceError, "%PDF- magic"),
        (response(b"", content_type="application/pdf"), CboSourceError, "empty"),
        (response(PDF, content_type="application/octet-stream"), CboSourceError, "Content-Type differs"),
        (response(CHALLENGE, 403, content_type="text/html;charset=utf-8"), CboChallengeError, "bot challenge"),
        (response(b"gone", 404, content_type="text/html; charset=UTF-8"), CboUnavailableError, "HTTP 404"),
    ],
)
def test_estimate_document_refusals_name_the_failed_check(answer, error, message):
    transport = Transport(answer)
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire_estimate_document(PDF_URL)
    assert raised.value.cbo_acquisition["operation"] == "estimate-document"


def test_a_redirected_document_is_not_the_document_the_locator_named():
    transport = Transport(response(b"moved", 302, content_type="text/html"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboSourceError, match="HTTP 302"):
        source.acquire_estimate_document(PDF_URL)


# --- configuration ----------------------------------------------------------------


def test_budget_and_client_configuration_are_explicit():
    for fields in (
        {"max_requests": 0},
        {"max_bytes": 64 * 1024**2 + 1},
        {"max_document_bytes": 0},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ):
        with pytest.raises(ValueError):
            CboBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        CboAcquirer(budget=(3, 4096, 7, 0), transport=Transport())
