"""CBO's per-Congress feed read as an observation whose Links name publications.

The feed is CBO's own ``<response>``/``<item key="N">`` XML, not RSS 2.0, and
carries no topic, budget-function, mandate or PAYGO field. ``/cost-estimates/xml``
and every PDF path answer a DataDome bot challenge, which this family names as a
challenge rather than a credential refusal because it holds no credential; no CBO
PDF is reachable keyless, so the PDF fixture bytes are built here, not published.
"""

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.cbo import (
    CBO_COST_ESTIMATES_FEED_URL,
    CboAcquirer,
    CboBudget,
    CboChallengeError,
    CboFeedBillError,
    CboSourceError,
    CboUnavailableError,
    cbo_cost_estimates_feed_locator,
    cbo_estimate_document_locator,
    cbo_feed_bills,
    cbo_per_congress_feed_locator,
    feed_item_bills,
    parse_cbo_cost_estimates_feed,
    title_bills,
)
from spicy_docs.sources.congress.bill_status import BillIdentity
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
    """An HTTPX response over the given bytes."""
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


# --- the feed CBO actually serves -------------------------------------------------


def test_pinned_feed_yields_publications_in_feed_order_with_publisher_spellings():
    """The pinned feed yields two items in feed order with publisher spellings; a procedural item's empty Bill_Number
    is None, not absent.
    """
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
    """The feed model exposes no channel header or topic, budget-function or paygo facets."""
    feed = parse_cbo_cost_estimates_feed(FEED)
    assert not hasattr(feed, "title") and not hasattr(feed, "last_build_date")
    assert not any(hasattr(item, name) for item in feed.items for name in ("topics", "budget_functions", "paygo"))


def test_empty_response_is_a_requested_empty_observation_not_a_refusal():
    """An empty ``<response>`` yields zero items rather than a refusal."""
    assert parse_cbo_cost_estimates_feed(b'<?xml version="1.0"?><response></response>').items == ()


def test_numeric_character_references_resolve_to_the_publishers_text():
    """Numeric character references resolve to the publisher's text."""
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
    """A feed failing its shape check raises CboSourceError naming that check."""
    with pytest.raises(CboSourceError, match=message):
        parse_cbo_cost_estimates_feed(body)


@pytest.mark.parametrize("max_bytes", [0, True, 64 * 1024**2 + 1])
def test_feed_bounds_are_explicit(max_bytes):
    """Zero, boolean and over-limit byte allowances are refused."""
    with pytest.raises(CboSourceError, match="max_bytes"):
        parse_cbo_cost_estimates_feed(MINIMAL, max_bytes=max_bytes)
    with pytest.raises(CboSourceError):
        parse_cbo_cost_estimates_feed(MINIMAL, max_bytes=len(MINIMAL) - 1)


# --- qualification against every real feed retained -------------------------------

RECEIPTS = Path.home() / "Work/corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14"
WALL_PROBES = Path.home() / "Work/corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-14/q3-cbo-bot-wall"
REFSPEC = Path.home() / "Work/RefSpec/tests/fixtures/cbo_topic_codes"
RETAINED = [
    (RECEIPTS / "09-116congress.body", 1259),
    (RECEIPTS / "06-117congress.body", 1191),
    (RECEIPTS / "06-118congress.body", 1533),
    (RECEIPTS / "02-119congress.body", 1192),
    (WALL_PROBES / "06-httpx-browser-per-congress-feed.body", 1192),
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


def test_item_position_is_a_per_capture_ordering_not_an_identity():
    """Two captures of the 119th feed nine hours apart, same 1,192 items, different bytes.

    They agree on every field of every item and on newest-first ordering, and
    disagree only on the order inside runs of items sharing one Date -- 76
    positions. So ``index``/``key`` is where an item sat in that capture, never
    a stable handle on it, and a digest change is not evidence the feed changed.
    """
    earlier, later = RECEIPTS / "02-119congress.body", WALL_PROBES / "06-httpx-browser-per-congress-feed.body"
    if not (earlier.exists() and later.exists()):
        pytest.skip("retained captures not present")
    first, second = (parse_cbo_cost_estimates_feed(path.read_bytes()) for path in (earlier, later))
    assert earlier.read_bytes() != later.read_bytes(), "different bytes"

    def field_of(feed):
        return {i.publication_id: (i.title, i.date, i.link, i.description, i.bill_number) for i in feed.items}

    assert field_of(first) == field_of(second), "every item, every field, unchanged"
    positions = [(a.publication_id, b.publication_id) for a, b in zip(first.items, second.items, strict=True) if a != b]
    assert positions, "the captures do differ in item order"
    dates = field_of(first)
    assert all(dates[a][1] == dates[b][1] for a, b in positions), "reordering happens only within one Date"


# --- locators ---------------------------------------------------------------------


def test_locators_are_the_publishers_own_spellings():
    """Locators return the publisher's own URLs unchanged."""
    assert cbo_cost_estimates_feed_locator() == CBO_COST_ESTIMATES_FEED_URL
    assert cbo_per_congress_feed_locator(119) == FEED_119_URL
    assert cbo_estimate_document_locator(PDF_URL) == PDF_URL


@pytest.mark.parametrize("congress", [0, 1000, True, "119", 119.0, None])
def test_per_congress_locator_refuses_anything_but_a_congress_number(congress):
    """Zero, oversized, boolean, string, float and None congress values are refused."""
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
    """A document locator outside official cbo.gov PDF URLs is refused."""
    with pytest.raises(CboSourceError, match="estimate document must be"):
        cbo_estimate_document_locator(url)


# --- acquisition ------------------------------------------------------------------


def test_acquirer_captures_exact_feed_bytes_keyless():
    """The acquirer captures exact feed bytes keyless, with identity encoding and no auth headers."""
    transport = Transport(response())
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_per_congress_feed(119)
    assert result.capture.body == FEED and result.capture.requested_url == FEED_119_URL
    assert len(result.feed.items) == 2 and result.request_count == 1 and result.budget == BUDGET
    assert "x-api-key" not in transport.calls[0].headers
    assert "authorization" not in transport.calls[0].headers
    assert transport.calls[0].headers["accept-encoding"] == "identity"


def test_a_call_may_narrow_the_byte_allowance_but_never_raise_it():
    """A call may narrow the byte allowance but never raise it."""
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
    """A wrong-shape or walled feed fails after one request, recording the per-congress-feed operation."""
    transport = Transport(answer)
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire_per_congress_feed(119)
    assert raised.value.cbo_acquisition["operation"] == "per-congress-feed"
    assert len(transport.calls) == 1


def test_a_200_that_is_not_the_expected_shape_retains_its_bytes():
    """A 200 that is not the expected shape retains its exact bytes in the refusal."""
    transport = Transport(response(b'<?xml version="1.0"?><response><item key="9"/></response>'))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboSourceError) as raised:
        source.acquire_per_congress_feed(119)
    assert raised.value.refused_response.response_bytes == b'<?xml version="1.0"?><response><item key="9"/></response>'


def test_the_walled_cost_estimates_route_is_recorded_as_a_challenge_not_a_credential_refusal():
    """The walled cost-estimates route is recorded as a challenge with its URL, not a credential refusal."""
    transport = Transport(response(CHALLENGE, 403, content_type="text/html;charset=utf-8"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboChallengeError) as raised:
        source.acquire_cost_estimates_feed()
    assert raised.value.url == CBO_COST_ESTIMATES_FEED_URL
    assert raised.value.cbo_acquisition["operation"] == "cost-estimates-feed"
    assert str(transport.calls[0].url) == CBO_COST_ESTIMATES_FEED_URL


def test_a_challenge_reaches_the_caller_with_its_bytes_because_the_route_is_keyless():
    """A keyless challenge reaches the caller with its bytes; the per-response nonce prevents digest pinning."""
    # Keyless routes retain the 401/403 body, so the wall's own answer is
    # evidence rather than an aborted capture with nothing in it. Its digest
    # cannot be pinned: the challenge carries a per-response nonce.
    transport = Transport(response(CHALLENGE, 403, content_type="text/html;charset=utf-8"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboChallengeError) as raised:
        source.acquire_estimate_document(PDF_URL)
    refused = raised.value.refused_response
    assert refused.response_bytes == CHALLENGE and refused.media_type == "text/html"
    assert b"Please enable JS" in refused.response_bytes, "a JS challenge; no header set passes it"
    assert raised.value.cbo_acquisition["url"] == PDF_URL


def test_an_injected_browser_backed_transport_is_all_the_document_route_still_needs():
    """The wall is the only thing missing: given a transport that answers, this route works.

    Every cbo.gov document path measured -- /publication/<id>, /system/files/*,
    /sites/default/files/*.pdf -- answered the DataDome challenge even to a
    complete browser-like header set, and CBO's markup names no other host. So
    the caller supplies a browser-backed transport; the locator grammar, the
    bounds and the identity proofs below are unchanged by where the bytes came from.
    """
    transport = Transport(response(PDF, content_type="application/pdf"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_estimate_document(PDF_URL)
    assert result.capture.body == PDF and result.capture.resolved_url == PDF_URL
    assert transport.calls[0].headers["user-agent"] == "spicy-docs-cbo-feed/1.0"


def test_the_cost_estimates_route_would_be_read_by_the_same_parser_if_it_ever_answered():
    """The cost-estimates route parses through the same feed parser if it answers."""
    transport = Transport(response(MINIMAL))
    with CboAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_cost_estimates_feed()
    assert result.capture.body == MINIMAL and result.feed.items[0].publication_id == "62589"


# --- the estimate document --------------------------------------------------------


def test_estimate_document_identity_is_proved_by_media_type_magic_and_final_url():
    """Estimate document identity is proved by media type, magic bytes and final URL, in one request."""
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
    """Estimate document refusals name the failed check and the estimate-document operation."""
    transport = Transport(answer)
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire_estimate_document(PDF_URL)
    assert raised.value.cbo_acquisition["operation"] == "estimate-document"


def test_a_redirected_document_is_not_the_document_the_locator_named():
    """A redirected document fails identity rather than being accepted."""
    transport = Transport(response(b"moved", 302, content_type="text/html"))
    with CboAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CboSourceError, match="HTTP 302"):
        source.acquire_estimate_document(PDF_URL)


# --- configuration ----------------------------------------------------------------


def test_budget_and_client_configuration_are_explicit():
    """Invalid budget values raise ValueError and a wrong transport type raises TypeError."""
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


# --- which bills a feed item names ------------------------------------------------

#: Every ``Bill_Number`` form in the 112th and 113th feeds (2026-09-28) and the
#: 116th-119th (2026-09-14), one real spelling each, with the bill it names.
#: Receipt: ``~/Work/corpora/fork-execution-2026-09-21/cbo-112-113/`` (``feed-shapes.json``,
#: ``other-feed-shapes.json``).
MAPPED_FORMS = (
    ("H.R. 8", ("hr", 8)),
    ("S. 2241", ("s", 2241)),
    ("H.J. Res. 118", ("hjres", 118)),
    ("H. J. Res. 48", ("hjres", 48)),
    ("H.J.Res. 124", ("hjres", 124)),
    ("H.J. Res 45", ("hjres", 45)),
    ("S.J.Res. 44", ("sjres", 44)),
    ("S.J. Res. 20", ("sjres", 20)),
    ("H. Con. Res. 92", ("hconres", 92)),
    ("H.Con.Res. 103", ("hconres", 103)),
    ("H.Con.Res 14", ("hconres", 14)),
    ("H. Con. Res 14", ("hconres", 14)),
    ("S. Con. Res. 33", ("sconres", 33)),
    ("H.R 260", ("hr", 260)),
    ("H.R.681", ("hr", 681)),
    ("H. R. 3350", ("hr", 3350)),
    ("H.r. 4679", ("hr", 4679)),
    ("S.559", ("s", 559)),
    ("S.  1591", ("s", 1591)),
)


@pytest.mark.parametrize(("bill_number", "expected"), MAPPED_FORMS)
def test_every_measured_bill_number_form_names_its_one_bill(bill_number, expected):
    """Each measured spelling maps to the one bill it names, in the feed's own Congress."""
    assert feed_item_bills(113, bill_number) == (BillIdentity(113, *expected),)


def test_an_empty_bill_number_names_no_bill_rather_than_refusing():
    """CBO's empty Bill_Number (a suspension-calendar notice, a reconciliation title) is a value, not a refusal."""
    assert feed_item_bills(112, None) == ()


@pytest.mark.parametrize(
    ("bill_number", "shape"),
    [
        ("700", "N"),  # 117th: no type to read
        ("S.A. 948", "S.A. N"),  # 116th: a Senate amendment, not a bill
        ("H.R. 7529,", "H.R. N,"),  # 119th: trailing text
        ("H.R. 1, H.R. 2", "H.R. N, H.R. N"),  # a list no feed has stated
        ("HR 5", "HR N"),
        ("H.R. 0", "H.R. N"),
        ("H.Res.Con. 4", "H.Res.Con. N"),
    ],
)
def test_a_bill_number_no_rule_maps_is_refused_with_its_shape(bill_number, shape):
    """A form outside the measured grammar refuses and names its shape, never guessing a type or splitting a list."""
    with pytest.raises(CboFeedBillError) as raised:
        feed_item_bills(113, bill_number)
    assert (raised.value.field, raised.value.shape) == ("bill_number", shape)
    assert isinstance(raised.value, CboSourceError)


#: Titles of 112th-113th items whose ``Bill_Number`` is empty, verbatim and cut at 60 characters where longer, and
#: the bill each leads with (receipt ``title-bill-set.json``).
TITLE_FORMS = (
    ("H.R. 4402, Critical Minerals Policy Act of 2012", ("hr", 4402)),
    ("S. 3326, a bill to amend the African Growth and Opportunity", ("s", 3326)),
    ("H. Con. Res. 44, a concurrent resolution authorizing the use", ("hconres", 44)),
    ("H.R. 6082, Congressional Replacement of President Obama’s En", ("hr", 6082)),
)


@pytest.mark.parametrize(("title", "expected"), TITLE_FORMS)
def test_a_title_that_leads_with_a_citation_names_that_bill(title, expected):
    """An item with an empty Bill_Number names the bill its title leads with, read by the Bill_Number grammar."""
    assert title_bills(113, title) == (BillIdentity(113, *expected),)


@pytest.mark.parametrize(
    "title",
    [
        "Sequester Replacement Reconciliation Act",
        "Public Law 112-8, Further Additional Continuing Appropriations Amendments, 2011",
        "The President&#039;s Supplemental Request for FY 2014 for the Southwest Border",
        "Agriculture Reform, Food, and Jobs Act of 2012",
        "Letter to the Honorable Chris Van Hollen Regarding a Proposed Amendment",
        # Synthetic: prose that holds a type letter before a number is not a citation.
        "Obama's 2013 budget, as U.S. 1 of the series",
    ],
)
def test_a_title_without_a_citation_names_no_bill(title):
    """A title that leads with prose names no bill; it is counted, not refused."""
    assert title_bills(112, title) == ()


@pytest.mark.parametrize(
    ("title", "shape"),
    [
        # 119th, 2026-09-14: the estimate is of provisions in a bill, not of the bill.
        ("Information Concerning Medicaid-Related Provisions in Title IV of H.R. 1", "not-at-start"),
        # Synthetic: no measured title cites two bills or leads with a non-bill abbreviation.
        ("H.R. 1 and S. 2, the Tax Relief Acts", "two-citations"),
        ("H.R. 5, as amended by H. Res. 6", "two-citations"),
        ("S.A. 948, an amendment to S. 1", "not-at-start"),
        ("H. Amdt. 5, an amendment", "unknown-form"),
        ("S. 2nd Session Report on Appropriations", "unknown-form"),
    ],
)
def test_an_ambiguous_title_is_refused_by_shape(title, shape):
    """A second bill, a citation after the start, or an abbreviation that is no bill type refuses rather than guess."""
    with pytest.raises(CboFeedBillError) as raised:
        title_bills(113, title)
    assert (raised.value.field, raised.value.shape) == ("title", shape)


def test_a_title_citing_its_own_bill_twice_is_not_ambiguous():
    """Synthetic: a repeat of the leading citation names the same bill, so it maps."""
    assert title_bills(113, "H.R. 3409, Stop the War on Coal Act (H.R. 3409)") == (BillIdentity(113, "hr", 3409),)


def test_a_feed_maps_to_a_sorted_bill_set_marked_by_how_each_was_found():
    """Two spellings of one bill fold onto it and every item's publication is kept. A title is read only where the
    Bill_Number is empty, a bill any Bill_Number names is marked so, and an item naming none or refused is counted."""
    items = [
        ("62001", "H.J. Res. 59", "T"),
        ("62002", "S. 12", "H.R. 9, a title the Bill_Number overrides"),
        ("62003", "", "Sequester Replacement Reconciliation Act"),
        ("62004", "H.J.Res. 59", "T"),
        ("62005", "S.A. 948", "T"),
        ("62006", "", "H.R. 9, a bill to name a post office"),
        ("62007", "", "S. 12, a second statement by title"),
        ("62008", "", "Information Concerning Provisions in Title IV of H.R. 1"),
    ]
    body = (
        b'<?xml version="1.0"?>\n<response>'
        + b"".join(
            f'<item key="{index}"><Title>{title}</Title><Date>Fri, 11 Sep 2026 17:00:00 -0400</Date>'
            f"<Link>https://www.cbo.gov/publication/{pub}</Link><Description></Description>"
            f"<Bill_Number>{number}</Bill_Number></item>".encode()
            for index, (pub, number, title) in enumerate(items)
        )
        + b"</response>"
    )
    named = cbo_feed_bills(parse_cbo_cost_estimates_feed(body), 113)
    assert [(b.identity, b.publication_ids, b.found_by) for b in named.bills] == [
        (BillIdentity(113, "hjres", 59), ("62001", "62004"), "bill_number"),
        (BillIdentity(113, "hr", 9), ("62006",), "title"),
        (BillIdentity(113, "s", 12), ("62002", "62007"), "bill_number"),
    ]
    assert (named.congress, named.unnamed) == (113, 1)
    assert named.refused == (("62005", "bill_number", "S.A. N"), ("62008", "title", "not-at-start"))
