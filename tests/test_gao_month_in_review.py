"""GAO's Month in Review and Annual Index pages are read, walked and re-read as the publisher's own product listing.

Pins the retained pages' teaser fields, pager shapes and decision splitting; refusals for a page that is not its
scope's page or disagrees with the scope's first page; and a resumable, budgeted, spaced walk through the real
Zyte transport over a fake provider.
"""

import inspect
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from spicy_docs.sources.gao import month_in_review
from spicy_docs.sources.gao.month_in_review import (
    CRAWL_DELAY_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_CONCURRENCY,
    GaoListingAcquirer,
    GaoListingBudget,
    GaoListingScope,
    GaoListingSourceError,
    collect_listing,
    main,
    parse_listing_page,
    parser,
    read_listing_run,
    walk_listing,
)
from spicy_docs.sources.zyte import ZyteHttpResponse, ZyteTransportError
from spicy_docs.transport.zyte import ZyteBudget, ZyteTransport

FIXTURES = Path(__file__).parent / "fixtures" / "listings" / "gao-month-in-review"
AUGUST = GaoListingScope(2026, 8)
AUGUST_PAGES = [(FIXTURES / f"2026-08-page-{index}.html").read_bytes() for index in range(4)]
START = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)
JUNE, JULY = GaoListingScope(2026, 6), GaoListingScope(2026, 7)


def page(body: bytes, *, scope: GaoListingScope = AUGUST, index: int = 0, **expected):
    return parse_listing_page(body, scope=scope, page_index=index, **expected)


class FakeZyte:
    """Serves fixture bytes for listing URLs the way Zyte answers them, and records every call."""

    def __init__(self, pages: dict[str, bytes], *, fail: set[str] = frozenset()):
        self.pages, self.fail, self.calls = pages, fail, []

    def fetch(self, url, *, timeout_seconds, max_bytes, mode):
        self.calls.append(url)
        if url in self.fail:
            raise ZyteTransportError("Zyte acquisition failed with HTTP 520 (/download/temporary-error)")
        return ZyteHttpResponse(
            url, url, 200, "text/html; charset=UTF-8", self.pages[url], mode, f"req-{len(self.calls)}"
        )


def august_site(**replace: bytes) -> dict[str, bytes]:
    return {AUGUST.page_url(index): replace.get(str(index), body) for index, body in enumerate(AUGUST_PAGES)}


def month_site(*scopes: GaoListingScope) -> dict[str, bytes]:
    """August's pages retitled as other months: only the title and canonical link name the month."""
    site: dict[str, bytes] = {}
    for scope in scopes:
        for index, body in enumerate(AUGUST_PAGES):
            renamed = body.replace(AUGUST.title.encode(), scope.title.encode()).replace(
                f'rel="canonical" href="{AUGUST.url}"'.encode(), f'rel="canonical" href="{scope.url}"'.encode()
            )
            site[scope.page_url(index)] = renamed
    return site


class Clock:
    """A clock that only moves when the walk sleeps."""

    def __init__(self, now: datetime = START):
        self.now, self.sleeps = now, []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += timedelta(seconds=seconds)


def walk(
    tmp_path,
    zyte: FakeZyte,
    *,
    requests: int = 10,
    clock: Clock | None = None,
    spacing: float = 0,
    scopes=(AUGUST,),
    concurrency: int = 1,
    max_consecutive_failures: int = 1,
    backoff: float = 60,
    made: list | None = None,
    real_wait: bool = False,
):
    """One walk over ``zyte``; ``real_wait`` leaves the spacing to the walk's own interruptible wait."""
    clock = clock or Clock()
    budget = ZyteBudget(requests)
    transport = ZyteTransport(zyte, max_bytes=4 * 1024 * 1024, timeout_seconds=30, budget=budget)

    def acquirers() -> GaoListingAcquirer:
        if made is not None:
            made.append(1)
        return GaoListingAcquirer(
            budget=GaoListingBudget(min_request_interval_seconds=0, timeout_seconds=30),
            transport=transport,
            clock=clock,
        )

    code = walk_listing(
        list(scopes),
        acquirers=acquirers,
        store=tmp_path / "store",
        receipts=tmp_path / "receipts.jsonl",
        zyte_budget=budget,
        proxy_record=transport.record_for,
        spacing_seconds=spacing,
        concurrency=concurrency,
        max_consecutive_failures=max_consecutive_failures,
        failure_backoff_seconds=backoff,
        clock=clock,
        sleep=None if real_wait else clock.sleep,
    )
    return code, [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]


def test_scope_names_the_page_gao_links_and_titles():
    """A scope names GAO's own URL, first page bare and later pages by the pager's query, and the page title."""
    assert AUGUST.url == "https://www.gao.gov/reports-testimonies/month-in-review/2026/August"
    assert AUGUST.page_url(0) == AUGUST.url and AUGUST.page_url(3) == AUGUST.url + "?page=3"
    assert AUGUST.title == "U.S. GAO - Month in Review, August 2026" and AUGUST.key == "2026-08"
    year = GaoListingScope.parse("2025")
    assert year.url.endswith("/month-in-review/2025") and year.month is None
    assert year.title == "U.S. GAO - Annual Index of Reports, Testimony and Correspondence (FY2025)"
    for bad in ("2026-13", "26", "2026/August", "2026-8"):
        with pytest.raises(GaoListingSourceError):
            GaoListingScope.parse(bad)


def test_first_page_states_its_last_page_and_each_teaser_as_spelled():
    """The first page's pager names its last page, and a teaser keeps GAO's label, heading, topic and both dates."""
    first = page(AUGUST_PAGES[0])
    assert (first.page_index, first.last_page_index, len(first.entries)) == (0, 3, 25)
    entry = first.entries[0]
    assert entry.topic == "Auditing and Financial Management"
    assert (entry.product_number, entry.product_id, entry.link) == (
        "GAO-26-108640",
        "gao-26-108640",
        "/products/gao-26-108640",
    )
    assert (entry.label, entry.heading) == (
        "College Athletics",
        "Most Programs Spend More Than They Generate in Revenue",
    )
    assert (entry.published, entry.released, entry.decision_numbers) == ("2026-07-14", "2026-08-05", ())


def test_last_pages_carry_no_last_link_and_are_their_own_last_page():
    """A last page marks itself current with no "Last" link, including a year's overflow pager with two teasers."""
    assert page(AUGUST_PAGES[3], index=3).last_page_index == 3
    tail = page((FIXTURES / "2025-page-49.html").read_bytes(), scope=GaoListingScope(2025), index=49)
    assert tail.last_page_index == 49 and len(tail.entries) == 2
    assert {entry.topic for entry in tail.entries} == {"Other Decision"}


def test_decisions_are_kept_apart_with_each_b_number_split():
    """A B-numbered teaser has no product id, and a teaser naming several B-numbers keeps each separately."""
    entries = [entry for body in AUGUST_PAGES for entry in page(body, index=AUGUST_PAGES.index(body)).entries]
    joint = next(entry for entry in entries if entry.product_number == "B-423916.2,B-423916.3")
    assert joint.product_id is None and joint.decision_numbers == ("B-423916.2", "B-423916.3")
    assert joint.link == "/products/b-423916.2%2Cb-423916.3" and joint.published is None
    assert all(
        (entry.product_id is None) == entry.product_number.startswith("B-")
        for entry in entries
        if entry.label != "Federal Agency Major Rule Report"
    )


def test_a_teaser_gao_gives_no_product_number_is_kept_apart_by_its_link():
    """2011's index lists an Antideficiency Act report with an empty number field: set apart, never a product."""
    scope = GaoListingScope(2011)
    body = (FIXTURES / "2011-page-64.html").read_bytes()
    listed = page(body, scope=scope, index=64)
    report = listed.entries[11]
    assert (report.product_number, report.product_id, report.decision_numbers) == (None, None, ())
    assert report.link == "/products/p00459" and report.topic == "Antideficiency Act Report"
    assert report.heading == "Antideficiency Act Reports: Fiscal Year 2010" and report.released == "2011-01-19"
    products, decisions, others = collect_listing([listed])
    assert [(item.link, item.product_number) for item in others] == [("/products/p00459", None)]
    assert "p00459" not in {product.product_id for product in products}
    assert all(decision.decision_numbers for decision in decisions)


#: The first decision teaser of August 2026's last page, respelled the four ways older indexes spell decisions (seen on
#: 2009-2012 and 2017 pages the 2026-09-28 backfill first refused).
DECISION = b'href="/products/b-424129.2"'
OLDER_DECISIONS = [
    (
        "/products/b-404896%2Cb-404896.2%2C",
        "B-404896,B-404896.2,",
        ("B-404896", "B-404896.2"),
    ),
    ("/products/b-235577.2-o.m.", "B-235577.2-O.M.", ("B-235577.2-O.M.",)),
    # 2010: GAO cut a long list mid-number, in the field and in the link alike.
    ("/products/b-403647%2Cb-403648%2Cb", "B-403647,B-403648,B", ("B-403647", "B-403648")),
    # 2020: Drupal's duplicate-path suffix on a decision's page.
    ("/products/b-331094-0", "B-331094", ("B-331094",)),
    (
        "/products/b-414056%2Cb-414056.2%2Cb-414056.",
        "B-414056,B-414056.2,B-414056.",
        ("B-414056", "B-414056.2", "B-414056."),
    ),
    ("/products/b-402003-b-402003.2", "B-402003; B-402003.2", ("B-402003", "B-402003.2")),
    (
        "/products/b-407312%2Cb-407372%2C-b-407382",
        "B-407312,B-407372, B-407382",
        ("B-407312", "B-407372", "B-407382"),
    ),
]


@pytest.mark.parametrize(("link", "number", "numbers"), OLDER_DECISIONS)
def test_older_decision_spellings_split_into_their_b_numbers(link, number, numbers):
    """A decision's link need only name its number letter for letter; its numbers split on commas and semicolons."""
    body = (
        AUGUST_PAGES[3]
        .replace(DECISION, f'href="{link}"'.encode(), 2)
        .replace(b">B-424129.2<", f">{number}<".encode(), 1)
    )
    entry = page(body, index=3).entries[0]
    assert (entry.link, entry.product_number, entry.decision_numbers, entry.product_id) == (link, number, numbers, None)


@pytest.mark.parametrize(("suffix", "accepted"), [("-0", True), ("-12", True), ("-x", False), ("0", False)])
def test_a_product_page_with_drupals_duplicate_path_suffix_keys_on_its_link(suffix, accepted):
    """2015 links GAO-16-75SP as ``/products/gao-16-75sp-0``: the product id is the page the listing links."""
    link = f"/products/gao-26-108640{suffix}"
    body = _first_teaser(b'href="/products/gao-26-108640"', f'href="{link}"'.encode()).replace(
        b'<h3 class="heading"><a href="/products/gao-26-108640">', f'<h3 class="heading"><a href="{link}">'.encode(), 1
    )
    if not accepted:
        with pytest.raises(GaoListingSourceError, match="other than its product number"):
            page(body)
        return
    entry = page(body).entries[0]
    assert (entry.product_id, entry.product_number, entry.link) == (f"gao-26-108640{suffix}", "GAO-26-108640", link)


def test_a_product_linked_by_its_prerelease_path_keys_on_its_number():
    """2020-2023 link some products as ``/prerelease/3mpz``; ``/products/gao-21-584`` is still the product's page."""
    body = AUGUST_PAGES[0].replace(b'href="/products/gao-26-108640"', b'href="/prerelease/3mpz"', 2)
    entry = page(body).entries[0]
    assert (entry.product_id, entry.product_number, entry.link) == (
        "gao-26-108640",
        "GAO-26-108640",
        "/prerelease/3mpz",
    )


@pytest.mark.parametrize(
    ("old", "link"),
    [(b'href="/products/b-424129.2"', "/prerelease/3mpz"), (b'href="/products/b-424129.2"', "/about/x")],
)
def test_a_decision_or_any_other_path_off_the_product_pages_still_refuses(old, link):
    """Only a numbered product may link its prerelease path; nothing may link outside the product pages."""
    with pytest.raises(GaoListingSourceError, match="does not link one product page"):
        page(AUGUST_PAGES[3].replace(old, f'href="{link}"'.encode(), 2), index=3)


def test_a_decision_linking_another_number_still_refuses():
    """Letters and digits must agree: a decision teaser linking another decision's page is refused."""
    body = AUGUST_PAGES[3].replace(DECISION, b'href="/products/b-424130.2"', 2)
    with pytest.raises(GaoListingSourceError, match="other than its product number"):
        page(body, index=3)


@pytest.mark.parametrize(("link", "number"), [("/products/2020-02", "2020-02"), ("/products/2020-02-0", "2020-02")])
def test_a_number_neither_gao_nor_b_is_a_legal_product_kept_apart(link, number):
    """GAO's Contract Appeals Board dockets (``2020-02``, some on a ``-0`` page) are listed as Other Decisions."""
    body = _first_teaser(b'href="/products/gao-26-108640" rel="bookmark"', f'href="{link}" rel="bookmark"'.encode())
    body = body.replace(
        b'<h3 class="heading"><a href="/products/gao-26-108640">', f'<h3 class="heading"><a href="{link}">'.encode(), 1
    )
    body = body.replace(b">GAO-26-108640<", f">{number}<".encode(), 1)
    entry = page(body).entries[0]
    assert (entry.product_id, entry.decision_numbers, entry.product_number) == (None, (), number)
    products, _, others = collect_listing([page(body)])
    assert number not in {product.product_number for product in products}
    assert [(item.link, item.product_number) for item in others] == [(link, number)]


def test_a_gao_numbered_product_under_a_legal_heading_is_still_a_product():
    """2012-2014 file major-rule reports numbered GAO-14-253R under a legal heading: GAO products all the same."""
    body = AUGUST_PAGES[3].replace(b'href="/products/b-424129.2"', b'href="/products/gao-14-253r"', 2)
    entry = page(body.replace(b">B-424129.2<", b">GAO-14-253R<", 1), index=3).entries[0]
    assert entry.topic == "Bid Protest Decision" and entry.product_id == "gao-14-253r"


MAJOR_RULE = b'href="/products/b-424129.2"'


def _product_teaser(
    body: bytes, *, link: str, number: str, label: str | None = None, heading: str | None = None
) -> bytes:
    """August's first teaser respelled as another product: its two links, number, and optionally label and heading."""
    head, tail = body[:FIRST_ARTICLE], body[FIRST_ARTICLE:]
    tail = tail.replace(b'href="/products/gao-26-108640"', f'href="{link}"'.encode(), 2)
    tail = tail.replace(b">GAO-26-108640<", f">{number}<".encode(), 1)
    if label is not None:
        tail = tail.replace(b'rel="bookmark">College Athletics<', f'rel="bookmark">{label}<'.encode(), 1)
    if heading is not None:
        tail = tail.replace(b">Most Programs Spend More Than They Generate in Revenue<", f">{heading}<".encode(), 1)
    return head + tail


def test_a_product_listed_on_its_page_and_on_a_suffixed_twin_is_one_product():
    """GAO-16-75SP is listed at ``gao-16-75sp`` and ``gao-16-75sp-0`` with the same fields: one product, the base page,
    carrying the twin's topics and scopes too."""
    base = page(AUGUST_PAGES[0])
    twin = (
        month_site(JULY)[JULY.page_url(0)]
        .replace(b'href="/products/gao-26-108640"', b'href="/products/gao-26-108640-0"')
        .replace(b">Auditing and Financial Management</h2>", b">Veterans</h2>", 1)
    )
    products, _, _ = collect_listing([base, page(twin, scope=JULY)])
    (listed,) = [product for product in products if product.product_number == "GAO-26-108640"]
    assert listed.product_id == "gao-26-108640" and listed.scopes == ("2026-08", "2026-07")
    assert listed.topics == ("Auditing and Financial Management", "Education", "Veterans")


def test_a_suffixed_page_with_its_own_fields_is_its_own_product():
    """``gao-14-280r-0`` is a VA major-rule report, ``gao-14-280r`` a Defense report, both numbered GAO-14-280R."""
    defense = page(
        _product_teaser(
            AUGUST_PAGES[0], link="/products/gao-14-280r", number="GAO-14-280R", label="Defense Infrastructure"
        )
    )
    veterans = page(
        _product_teaser(
            AUGUST_PAGES[0],
            link="/products/gao-14-280r-0",
            number="GAO-14-280R",
            label="Federal Agency Major Rule Report",
            heading="Department of Veterans Affairs: Copayments for Medications",
        )
    )
    products, _, _ = collect_listing([defense, veterans])
    listed = {product.product_id: product.label for product in products if product.product_number == "GAO-14-280R"}
    assert listed == {"gao-14-280r": "Defense Infrastructure", "gao-14-280r-0": "Federal Agency Major Rule Report"}


def test_a_b_numbered_major_rule_report_is_a_product_keyed_on_its_page():
    """The owner's exception: every major-rule report is a product, B-numbered from April 2017, keyed on its page."""
    listed = page(AUGUST_PAGES[3], index=3)
    reports = [entry for entry in listed.entries if entry.label == "Federal Agency Major Rule Report"]
    assert reports and all(entry.product_id == unquote(entry.link.removeprefix("/products/")) for entry in reports)
    assert all(entry.decision_numbers == () and entry.product_number.startswith("B-") for entry in reports)
    assert all(entry.decision_numbers for entry in listed.entries if entry.label != "Federal Agency Major Rule Report")


@pytest.mark.parametrize(("link", "number"), [("/products/p00459", ""), ("/products/2020-02", "2020-02")])
def test_the_major_rule_label_makes_no_product_of_a_page_numbered_neither_gao_nor_b(link, number):
    """The exception reaches GAO- and B-numbered teasers only: labelled so, a numberless or docket page stays apart."""
    body = _product_teaser(AUGUST_PAGES[0], link=link, number=number, label="Federal Agency Major Rule Report")
    listed = page(body)
    assert listed.entries[0].product_id is None and listed.entries[0].decision_numbers == ()
    assert [item.link for item in collect_listing([listed])[2]] == [link]


def test_a_b_number_under_a_topic_heading_is_still_a_decision():
    """B-310950.2 (2009) is listed under Budget and Spending; the heading does not make it a product."""
    body = _product_teaser(AUGUST_PAGES[0], link="/products/b-310950.2", number="B-310950.2", label="Legal")
    entry = page(body).entries[0]
    assert entry.topic == "Auditing and Financial Management" and entry.decision_numbers == ("B-310950.2",)
    assert entry.product_id is None


def test_a_decision_link_must_spell_its_number_token_for_token():
    """``B-4241292`` is not the page ``b-424129.2``: the letters and digits agree but the tokens do not."""
    body = AUGUST_PAGES[3].replace(b">B-424129.2<", b">B-4241292<", 1)
    with pytest.raises(GaoListingSourceError, match="other than its product number"):
        page(body, index=3)


def test_the_polite_defaults_are_one_worker_and_the_sites_crawl_delay():
    """The reviewed default path is serial and 420 s apart, in the library, the budget and the command alike."""
    parameters = inspect.signature(walk_listing).parameters
    assert (
        parameters["concurrency"].default == 1 and parameters["spacing_seconds"].default == CRAWL_DELAY_SECONDS == 420
    )
    assert parameters["max_consecutive_failures"].default == 1
    assert GaoListingBudget().min_request_interval_seconds == 420
    args = parser().parse_args(
        ["walk", "--scope", "2025", "--store", "s", "--receipts", "r", "--max-zyte-requests", "1"]
    )
    assert (args.delay_seconds, args.concurrency, args.max_consecutive_failures) == (420, 1, 1)


def test_the_command_spaces_requests_once_in_the_walk_not_again_in_the_acquirer(tmp_path, monkeypatch):
    """The walk owns spacing, across runs; the command's acquirers carry none of their own."""
    seen = {}

    def capture(scopes, **kwargs):
        seen.update(kwargs, acquirer=kwargs["acquirers"]())
        return 0

    monkeypatch.setenv("ZYTE_TOKEN", "test-token-1234567890")
    monkeypatch.setattr(month_in_review, "walk_listing", capture)
    args = ["walk", "--scope", "2025", "--store", str(tmp_path / "s"), "--receipts", str(tmp_path / "r")]
    assert main([*args, "--max-zyte-requests", "1", "--delay-seconds", "7"]) == 0
    assert seen["spacing_seconds"] == 7 and seen["acquirer"].budget.min_request_interval_seconds == 0


def test_a_page_cut_off_mid_teaser_refuses_as_incomplete():
    """A body cut inside a teaser is refused, never read as the teasers before the cut."""
    cut = AUGUST_PAGES[0][: AUGUST_PAGES[0].index(b"<article", FIRST_ARTICLE + 10) + 200]
    with pytest.raises(GaoListingSourceError, match="markup is incomplete"):
        page(cut)


def test_a_pager_deeper_than_the_bound_refuses():
    """A last page past ``max_last_page_index`` is refused rather than walked."""
    with pytest.raises(GaoListingSourceError, match="runs past page index 2"):
        page(AUGUST_PAGES[0], max_last_page_index=2)


def test_receipts_that_disagree_on_a_scopes_last_page_refuse(tmp_path):
    """Two retained pages of one scope stating different last pages cannot both be the listing."""
    walk(tmp_path, FakeZyte(august_site()))
    receipts = tmp_path / "receipts.jsonl"
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    rows[2]["last_page_index"] = 4
    receipts.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(GaoListingSourceError, match="disagree on scope 2026-08's last page"):
        read_listing_run(receipts, tmp_path / "store")


def test_a_scope_missing_only_its_last_page_is_unfinished(tmp_path):
    """Pages 1-3 of four retained is not a finished scope."""
    walk(tmp_path, FakeZyte(august_site()), requests=3)
    run = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    assert run.incomplete_scopes == ("2026-08",) and run.pages == ()


def test_a_page_read_back_from_another_url_refuses(tmp_path):
    """A receipt naming another URL for a page is refused on read-back, whatever its bytes."""
    walk(tmp_path, FakeZyte(august_site()))
    receipts = tmp_path / "receipts.jsonl"
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    rows[2]["request_url"] = AUGUST.page_url(2)
    receipts.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(GaoListingSourceError, match="requested at another URL"):
        read_listing_run(receipts, tmp_path / "store")


def test_a_repeated_scope_is_walked_once_by_no_more_workers_than_scopes(tmp_path):
    """``--scope 2026-08`` twice pays Zyte once, and four workers for one scope open one acquirer."""
    made: list = []
    zyte = FakeZyte(august_site())
    code, _ = walk(tmp_path, zyte, scopes=(AUGUST, AUGUST), concurrency=4, made=made)
    assert code == 0 and zyte.calls == [AUGUST.page_url(index) for index in range(4)] and len(made) == 1


def test_concurrency_is_capped_at_eight():
    """No walk runs more than eight workers, the cap the guide states."""
    assert MAX_CONCURRENCY == 8
    with pytest.raises(ValueError, match="concurrency"):
        walk_listing(
            [AUGUST],
            acquirers=lambda: None,
            store=Path("unused"),
            receipts=Path("unused"),
            zyte_budget=ZyteBudget(1),
            concurrency=9,
        )


def test_the_backoff_doubles_up_to_its_ceiling(tmp_path):
    """Failures in a row pause twice as long each time, never past the ceiling."""
    site = month_site(JUNE, JULY, AUGUST)
    clock = Clock()
    walk(
        tmp_path,
        FakeZyte(site, fail=set(site)),
        clock=clock,
        scopes=(JUNE, JULY, AUGUST),
        max_consecutive_failures=3,
        backoff=600,
    )
    assert clock.sleeps == [600.0, MAX_BACKOFF_SECONDS] and MAX_BACKOFF_SECONDS < 1200


def test_an_interrupt_stops_the_workers_writes_a_stopped_row_and_propagates(tmp_path, monkeypatch):
    """Ctrl-C while both workers wait out the spacing releases them at once: no request, a stopped row, then raised."""
    # A contact recorded now makes each worker's first request wait out the whole spacing.
    earlier = {"kind": "failed", "scope": "2026-06", "page_index": 0, "attempted_at": "2026-09-28T17:00:00Z"}
    (tmp_path / "receipts.jsonl").write_text(json.dumps(earlier) + "\n")
    asked = threading.Semaphore(0)

    class Waiting(Clock):
        """A worker asks the time once, after reserving its request and just before it waits out the spacing."""

        def __call__(self) -> datetime:
            asked.release()
            return super().__call__()

    real_join = threading.Thread.join
    interrupted: list = []

    def join(thread, timeout=None):
        if not interrupted:
            interrupted.append(thread)
            assert asked.acquire(timeout=10) and asked.acquire(timeout=10)
            raise KeyboardInterrupt
        return real_join(thread, timeout)

    monkeypatch.setattr(month_in_review.threading.Thread, "join", join)
    zyte = FakeZyte(month_site(JUNE, JULY, AUGUST))
    with pytest.raises(KeyboardInterrupt):
        walk(
            tmp_path,
            zyte,
            requests=20,
            clock=Waiting(),
            spacing=30,
            real_wait=True,
            scopes=(JUNE, JULY, AUGUST),
            concurrency=2,
        )
    rows = [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert zyte.calls == [] and rows[-1]["kind"] == "stopped" and "interrupted" in rows[-1]["reason"]
    assert not [thread for thread in threading.enumerate() if thread.name.startswith("gao-listing-")]


def test_the_transport_names_the_record_for_each_url():
    """The walk looks a page's Zyte record up by its URL, not by scanning every record so far."""
    transport = ZyteTransport(FakeZyte(august_site()), max_bytes=4 * 1024 * 1024, timeout_seconds=30)
    with httpx.Client(transport=transport) as client:
        for index in (0, 1, 0):
            client.get(AUGUST.page_url(index))
    assert transport.record_for(AUGUST.page_url(0)).zyte_request_id == "req-3"
    assert transport.record_for(AUGUST.page_url(1)).zyte_request_id == "req-2"
    assert transport.record_for(AUGUST.page_url(3)) is None


def test_the_oldest_year_probed_keeps_its_older_number_forms():
    """2009's index reads with its own pager depth and GAO's older report, testimony and correspondence ids."""
    first = page((FIXTURES / "2009-page-0.html").read_bytes(), scope=GaoListingScope(2009))
    assert first.last_page_index == 87 and len(first.entries) == 25
    ids = {entry.product_id for entry in first.entries}
    assert "gao-09-445" in ids and any(i.endswith("t") for i in ids) and any(i.endswith("r") for i in ids)


def test_a_whole_month_lists_each_product_once_with_every_topic():
    """August's four pages hold 100 teasers: 33 products and 40 decisions, each once, topics in listed order."""
    pages = [page(body, index=index) for index, body in enumerate(AUGUST_PAGES)]
    assert sum(len(p.entries) for p in pages) == 100
    products, decisions, others = collect_listing(pages)
    assert (len(products), len(decisions), len(others)) == (43, 30, 0)
    major_rule = [product for product in products if product.product_number.startswith("B-")]
    assert len(major_rule) == 10 and {product.label for product in major_rule} == {"Federal Agency Major Rule Report"}
    assert all(product.product_id == product.product_number.lower() for product in major_rule)
    college = next(product for product in products if product.product_id == "gao-26-108640")
    assert college.topics == ("Auditing and Financial Management", "Education") and college.scopes == ("2026-08",)
    assert college.title == "College Athletics: Most Programs Spend More Than They Generate in Revenue"
    receipts = next(product for product in products if product.product_id == "gao-26-108615")
    # GAO wrote non-breaking spaces into this heading, and the feed's title keeps them; so does the listing's.
    assert receipts.heading.count("\xa0") == 3 and "  " not in receipts.heading


def test_a_product_linked_two_ways_is_one_product():
    """2020-2023 link a product by its prerelease path in one place and its page in another: one product."""
    first = page(AUGUST_PAGES[0])
    again = page(AUGUST_PAGES[0].replace(b'href="/products/gao-26-108640"', b'href="/prerelease/3mpz"', 2))
    products, _, _ = collect_listing([first, again])
    assert [product.product_id for product in products].count("gao-26-108640") == 1


def test_two_decision_pages_sharing_a_b_number_are_two_decisions():
    """2019-2021 give one B-number two pages (``b-331093`` and ``b-331093-0``), dated apart: two decisions."""
    first = page(AUGUST_PAGES[3], index=3)
    second = page(
        AUGUST_PAGES[3]
        .replace(b'href="/products/b-424129.2"', b'href="/products/b-424129.2-0"', 2)
        .replace(b"Publicly Released: Aug 18, 2026.", b"Publicly Released: Sep 01, 2026.", 1),
        index=3,
    )
    _, decisions, _ = collect_listing([first, second])
    shared = [decision for decision in decisions if decision.product_number == "B-424129.2"]
    assert sorted((decision.link, decision.released) for decision in shared) == [
        ("/products/b-424129.2", "2026-08-18"),
        ("/products/b-424129.2-0", "2026-09-01"),
    ]


def test_one_product_listed_with_differing_fields_refuses():
    """The same product stated twice with different dates is refused rather than either spelling chosen."""
    first = page(AUGUST_PAGES[0])
    edited = page(AUGUST_PAGES[0].replace(b"Publicly Released: Aug 05, 2026.", b"Publicly Released: Aug 06, 2026.", 1))
    with pytest.raises(GaoListingSourceError, match="differing fields"):
        collect_listing([first, edited])


FIRST_ARTICLE = AUGUST_PAGES[0].index(b"<article")


def _first_teaser(old: bytes, new: bytes) -> bytes:
    """Replace ``old`` once, inside the first teaser only."""
    return AUGUST_PAGES[0][:FIRST_ARTICLE] + AUGUST_PAGES[0][FIRST_ARTICLE:].replace(old, new, 1)


@pytest.mark.parametrize(
    ("body", "kwargs", "message"),
    [
        (AUGUST_PAGES[0], {"scope": GaoListingScope(2026, 7)}, "is not titled"),
        (AUGUST_PAGES[0], {"index": 1}, "does not mark page 1"),
        (AUGUST_PAGES[0], {"expected_last_page_index": 4}, "changed shape"),
        (AUGUST_PAGES[0], {"expected_page_size": 24}, "holds 25 teasers"),
        (AUGUST_PAGES[0].replace(b'rel="canonical"', b'rel="shortlink"'), {}, "canonical URL"),
        (AUGUST_PAGES[0].replace(b"<article", b"<section").replace(b"</article>", b"</section>"), {}, "no teaser"),
        (AUGUST_PAGES[0].replace(b"node--type-product", b"node--type-page", 1), {}, "not a product"),
        (AUGUST_PAGES[0].replace(b'<h2 id="auditing-and-financial-management">', b"<p>", 1), {}, "before any heading"),
        (_first_teaser(b'<h3 class="heading">', b'<h3 class="subheading">'), {}, "lacks"),
        (
            _first_teaser(
                b"</header>", b'<div class="field--name-field-docdate">Publicly Released: Aug 05, 2026.</div></header>'
            ),
            {},
            "repeats",
        ),
        (
            _first_teaser(
                b'href="/products/gao-26-108640" rel="bookmark"', b'href="/products/gao-26-108641" rel="bookmark"'
            ),
            {},
            "does not link one",
        ),
        (_first_teaser(b"Published: Jul 14, 2026.", b"Published: 14 July 2026"), {}, "Mon DD, YYYY"),
        (
            AUGUST_PAGES[1][: AUGUST_PAGES[1].index(b'<nav aria-label="Pagination"')] + b"</main></body></html>",
            {"index": 1},
            "has no pager",
        ),
    ],
)
def test_a_page_that_is_not_its_scopes_page_refuses(body, kwargs, message):
    """A page refuses when it names another scope or page, moved, or lacks the fields it must state."""
    with pytest.raises(GaoListingSourceError, match=message):
        page(body, **kwargs)


def test_a_walk_retains_every_page_and_reads_back_verified(tmp_path):
    """A walk requests each page once, in order, keeps its bytes and Zyte request id, and reads back verified."""
    zyte = FakeZyte(august_site())
    code, rows = walk(tmp_path, zyte)
    assert code == 0 and zyte.calls == [AUGUST.page_url(index) for index in range(4)]
    assert [row["kind"] for row in rows] == ["started", "page", "page", "page", "page", "complete"]
    pages = [row for row in rows if row["kind"] == "page"]
    assert [row["zyte_request_id"] for row in pages] == ["req-1", "req-2", "req-3", "req-4"]
    assert {row["proxied_client"] for row in pages} == {"zyte"} and pages[0]["last_page_index"] == 3
    run = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    assert run.complete_scopes == ("2026-08",) and run.incomplete_scopes == ()
    assert (len(run.pages), len(run.products), len(run.decisions)) == (4, 43, 30)
    assert [retained.capture.body for retained in run.pages] == AUGUST_PAGES
    assert run.pages[0].capture.requested_url == AUGUST.url and run.pages[0].zyte_request_id == "req-1"

    again = FakeZyte(august_site())
    code, rows = walk(tmp_path, again)
    assert code == 0 and again.calls == [] and rows[-1]["kind"] == "complete"


def test_a_walk_stops_at_its_zyte_budget_and_resumes_where_it_stopped(tmp_path):
    """The Zyte budget stops a walk cleanly; the next run fetches only the missing pages, and only then is it read."""
    code, rows = walk(tmp_path, FakeZyte(august_site()), requests=2)
    assert code == 0 and rows[-1]["kind"] == "stopped"
    partial = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    assert partial.incomplete_scopes == ("2026-08",) and partial.products == () and partial.pages == ()
    zyte = FakeZyte(august_site())
    assert walk(tmp_path, zyte, requests=2, scopes=(AUGUST, GaoListingScope(2025)))[0] == 0
    assert zyte.calls == [AUGUST.page_url(2), AUGUST.page_url(3)]
    run = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    # A scope the walk was asked for but never reached reads as unfinished, not as absent.
    assert run.complete_scopes == ("2026-08",) and run.incomplete_scopes == ("2025",) and len(run.products) == 43


def test_a_failed_page_stops_the_walk_and_is_retried_on_resume(tmp_path):
    """A provider failure is recorded and stops the walk; resuming retries that page and continues."""
    code, rows = walk(tmp_path, FakeZyte(august_site(), fail={AUGUST.page_url(2)}))
    (failed,) = [row for row in rows if row["kind"] == "failed"]
    assert code == 1 and failed["page_index"] == 2 and rows[-1]["kind"] == "stopped"
    assert "520" in failed["error"] and failed["error_type"] == "ZyteTransportError"
    zyte = FakeZyte(august_site())
    assert walk(tmp_path, zyte)[0] == 0 and zyte.calls == [AUGUST.page_url(2), AUGUST.page_url(3)]


def test_a_listing_that_moves_restarts_its_scope_once_then_stops_it_by_name(tmp_path):
    """A pager that changes shape restarts the scope from page 0 once; moving again stops it by name, for good."""
    moved = AUGUST_PAGES[2].replace(
        b'href="?page=3" class="usa-pagination__link usa-pagination__next-page" aria-label="Last page"',
        b'href="?page=4" class="usa-pagination__link usa-pagination__next-page" aria-label="Last page"',
    )
    assert moved != AUGUST_PAGES[2]
    zyte = FakeZyte(august_site(**{"2": moved}))
    code, rows = walk(tmp_path, zyte)
    pages = [AUGUST.page_url(index) for index in (0, 1, 2)]
    assert code == 1 and zyte.calls == pages + pages
    moves = [row for row in rows if row["kind"] == "moved"]
    (failed,) = [row for row in rows if row["kind"] == "failed"]
    assert [row["page_index"] for row in moves] == [2, 2] and failed["scope"] == "2026-08"
    assert "changed shape" in failed["error"]
    assert failed["refused_evidence"]["stage"] == "source-validation"
    assert (
        tmp_path / "store" / "sha256" / failed["refused_evidence"]["sha256"].removeprefix("sha256:")
    ).read_bytes() == moved
    assert rows[-1]["kind"] == "stopped" and rows[-1]["unfinished"] == ["2026-08"] and "moved" in rows[-1]["reason"]

    again = FakeZyte(august_site())
    code, rows = walk(tmp_path, again)
    assert code == 1 and again.calls == [] and rows[-1]["unfinished"] == ["2026-08"] and "2026-08" in rows[-1]["reason"]


def test_parallel_periods_fetch_each_page_once_and_one_periods_failure_spares_the_others(tmp_path):
    """Periods walk in parallel; a failure stops only its own period, and the others' pages are all kept."""
    site = month_site(JUNE, JULY, AUGUST)
    zyte = FakeZyte(site, fail={JULY.page_url(1)})
    code, rows = walk(tmp_path, zyte, scopes=(JUNE, JULY, AUGUST), concurrency=3, max_consecutive_failures=3)
    assert code == 1 and len(zyte.calls) == len(set(zyte.calls)) == 10
    assert [(row["scope"], row["page_index"]) for row in rows if row["kind"] == "failed"] == [("2026-07", 1)]
    run = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    assert set(run.complete_scopes) == {"2026-06", "2026-08"} and run.incomplete_scopes == ("2026-07",)
    assert rows[-1]["kind"] == "stopped" and rows[-1]["unfinished"] == ["2026-07"]

    again = FakeZyte(site)
    code, rows = walk(tmp_path, again, scopes=(JUNE, JULY, AUGUST), concurrency=3)
    assert code == 0 and sorted(again.calls) == sorted(JULY.page_url(index) for index in (1, 2, 3))
    run = read_listing_run(tmp_path / "receipts.jsonl", tmp_path / "store")
    assert len(run.complete_scopes) == 3 and len(run.pages) == 12 and len(run.products) == 43
    assert {product.scopes for product in run.products} == {("2026-06", "2026-07", "2026-08")}


def test_the_zyte_budget_is_an_exact_ceiling_under_concurrency(tmp_path):
    """Parallel workers never start more requests than the budget, however they interleave."""
    zyte = FakeZyte(month_site(JUNE, JULY, AUGUST))
    code, rows = walk(tmp_path, zyte, requests=5, scopes=(JUNE, JULY, AUGUST), concurrency=3)
    assert code == 0 and len(zyte.calls) == 5 and rows[-1]["kind"] == "stopped"
    assert "budget" in rows[-1]["reason"] and sum(row["kind"] == "page" for row in rows) == 5


def test_consecutive_failures_back_off_and_then_stop_every_period(tmp_path):
    """Each failure pauses the walk, twice as long as the last, and enough in a row stop it before any other period."""
    site = month_site(JUNE, JULY, AUGUST)
    clock = Clock()
    zyte = FakeZyte(site, fail=set(site))
    code, rows = walk(tmp_path, zyte, clock=clock, scopes=(JUNE, JULY, AUGUST), max_consecutive_failures=3)
    assert code == 1 and zyte.calls == [JUNE.page_url(0), JULY.page_url(0), AUGUST.page_url(0)]
    assert clock.sleeps == [60.0, 120.0] and not [row for row in rows if row["kind"] == "page"]
    assert rows[-1]["kind"] == "stopped" and "3 consecutive failures" in rows[-1]["reason"]


def test_one_worker_stops_at_its_first_failure_by_default(tmp_path):
    """The default, one worker and one failure allowed, stops the whole walk at the first failure."""
    zyte = FakeZyte(month_site(JUNE, JULY), fail={JUNE.page_url(1)})
    code, rows = walk(tmp_path, zyte, scopes=(JUNE, JULY))
    assert code == 1 and zyte.calls == [JUNE.page_url(0), JUNE.page_url(1)]
    assert rows[-1]["unfinished"] == ["2026-06", "2026-07"]


def test_requests_are_spaced_from_the_last_recorded_contact_across_runs(tmp_path):
    """The first request waits out the spacing left since the receipts' last contact; later ones wait it whole."""
    earlier = {"kind": "failed", "scope": "2026-08", "page_index": 0, "attempted_at": "2026-09-28T16:58:20Z"}
    (tmp_path / "receipts.jsonl").write_text(json.dumps(earlier) + "\n")
    clock = Clock()
    assert walk(tmp_path, FakeZyte(august_site()), clock=clock, spacing=420)[0] == 0
    assert clock.sleeps == [320.0, 420.0, 420.0, 420.0]


def test_a_retained_page_that_differs_from_its_receipt_refuses(tmp_path):
    """Reading back refuses a receipt whose recorded size no longer matches the retained bytes."""
    walk(tmp_path, FakeZyte(august_site()))
    receipts = tmp_path / "receipts.jsonl"
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    rows[1]["bytes"] += 1
    receipts.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(GaoListingSourceError, match="differs from its receipt"):
        read_listing_run(receipts, tmp_path / "store")


def test_the_command_reads_a_walk_and_refuses_a_walk_without_a_token(tmp_path, monkeypatch, capsys):
    """``read`` prints every product and decision once; ``walk`` without ZYTE_TOKEN exits non-zero before any request."""
    walk(tmp_path, FakeZyte(august_site()))
    output = tmp_path / "listed.jsonl"
    assert (
        main(
            [
                "read",
                "--store",
                str(tmp_path / "store"),
                "--receipts",
                str(tmp_path / "receipts.jsonl"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    listed = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["kind"] for row in listed].count("product") == 43 and len(listed) == 73
    monkeypatch.delenv("ZYTE_TOKEN", raising=False)
    args = ["walk", "--scope", "2026-08", "--store", str(tmp_path / "s2"), "--receipts", str(tmp_path / "r2.jsonl")]
    assert main([*args, "--max-zyte-requests", "1"]) == 1
    assert "ZYTE_TOKEN" in capsys.readouterr().err and not (tmp_path / "r2.jsonl").exists()
