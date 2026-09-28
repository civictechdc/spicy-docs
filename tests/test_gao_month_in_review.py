"""GAO's Month in Review and Annual Index pages are read, walked and re-read as the publisher's own product listing.

Pins the retained pages' teaser fields, pager shapes and decision splitting; refusals for a page that is not its
scope's page or disagrees with the scope's first page; and a resumable, budgeted, spaced walk through the real
Zyte transport over a fake provider.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spicy_docs.sources.gao.month_in_review import (
    GaoListingAcquirer,
    GaoListingBudget,
    GaoListingScope,
    GaoListingSourceError,
    collect_listing,
    main,
    parse_listing_page,
    read_listing_run,
    walk_listing,
)
from spicy_docs.sources.zyte import ZyteHttpResponse, ZyteTransportError
from spicy_docs.transport.zyte import ZyteBudget, ZyteTransport

FIXTURES = Path(__file__).parent / "fixtures" / "listings" / "gao-month-in-review"
AUGUST = GaoListingScope(2026, 8)
AUGUST_PAGES = [(FIXTURES / f"2026-08-page-{index}.html").read_bytes() for index in range(4)]
START = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)


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
):
    clock = clock or Clock()
    budget = ZyteBudget(requests)
    transport = ZyteTransport(zyte, max_bytes=4 * 1024 * 1024, timeout_seconds=30, budget=budget)

    def acquirers() -> GaoListingAcquirer:
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
        proxy_records=lambda: transport.records,
        spacing_seconds=spacing,
        concurrency=concurrency,
        max_consecutive_failures=max_consecutive_failures,
        failure_backoff_seconds=60,
        clock=clock,
        sleep=clock.sleep,
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
    assert all((entry.product_id is None) == entry.product_number.startswith("B-") for entry in entries)


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
    products, decisions = collect_listing(pages)
    assert (len(products), len(decisions)) == (33, 40)
    college = next(product for product in products if product.product_id == "gao-26-108640")
    assert college.topics == ("Auditing and Financial Management", "Education") and college.scopes == ("2026-08",)
    assert college.title == "College Athletics: Most Programs Spend More Than They Generate in Revenue"
    receipts = next(product for product in products if product.product_id == "gao-26-108615")
    # GAO wrote non-breaking spaces into this heading, and the feed's title keeps them; so does the listing's.
    assert receipts.heading.count("\xa0") == 3 and "  " not in receipts.heading


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
        (_first_teaser(b"field--name-field-product-number", b"field--name-field-other"), {}, "lacks"),
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
    assert (len(run.pages), len(run.products), len(run.decisions)) == (4, 33, 40)
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
    assert run.complete_scopes == ("2026-08",) and run.incomplete_scopes == ("2025",) and len(run.products) == 33


def test_a_failed_page_stops_the_walk_and_is_retried_on_resume(tmp_path):
    """A provider failure is recorded and stops the walk; resuming retries that page and continues."""
    code, rows = walk(tmp_path, FakeZyte(august_site(), fail={AUGUST.page_url(2)}))
    (failed,) = [row for row in rows if row["kind"] == "failed"]
    assert code == 1 and failed["page_index"] == 2 and rows[-1]["kind"] == "stopped"
    assert "520" in failed["error"] and failed["error_type"] == "ZyteTransportError"
    zyte = FakeZyte(august_site())
    assert walk(tmp_path, zyte)[0] == 0 and zyte.calls == [AUGUST.page_url(2), AUGUST.page_url(3)]


def test_a_pager_that_changes_shape_mid_walk_refuses_and_keeps_the_page(tmp_path):
    """A later page whose pager states another last page refuses the walk and retains the refused bytes."""
    moved = AUGUST_PAGES[2].replace(
        b'href="?page=3" class="usa-pagination__link usa-pagination__next-page" aria-label="Last page"',
        b'href="?page=4" class="usa-pagination__link usa-pagination__next-page" aria-label="Last page"',
    )
    assert moved != AUGUST_PAGES[2]
    code, rows = walk(tmp_path, FakeZyte(august_site(**{"2": moved})))
    (failed,) = [row for row in rows if row["kind"] == "failed"]
    assert code == 1 and "changed shape" in failed["error"]
    assert failed["refused_evidence"]["stage"] == "source-validation"
    assert (
        tmp_path / "store" / "sha256" / failed["refused_evidence"]["sha256"].removeprefix("sha256:")
    ).read_bytes() == moved


JUNE, JULY = GaoListingScope(2026, 6), GaoListingScope(2026, 7)


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
    assert len(run.complete_scopes) == 3 and len(run.pages) == 12 and len(run.products) == 33
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
    assert [row["kind"] for row in listed].count("product") == 33 and len(listed) == 73
    monkeypatch.delenv("ZYTE_TOKEN", raising=False)
    args = ["walk", "--scope", "2026-08", "--store", str(tmp_path / "s2"), "--receipts", str(tmp_path / "r2.jsonl")]
    assert main([*args, "--max-zyte-requests", "1"]) == 1
    assert "ZYTE_TOKEN" in capsys.readouterr().err and not (tmp_path / "r2.jsonl").exists()
