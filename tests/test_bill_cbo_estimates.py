"""CBO estimates from Congress.gov's bill record: the reader, its refusals, the congress_api rows and the harvest.

The two fixtures are complete bill-detail responses recorded 2026-09-28 with the key sent only as ``X-Api-Key``
(``tests/fixtures/listings/README.md``): 113 H.R. 2810 lists two estimates and two report parts, and 113 S. 135,
reported but named by no CBO feed item, lists none.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.interpretation.bill_family import build_congress_api_cost_estimates
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.schemas import CBO_COST_ESTIMATES
from spicy_docs.schemas.cost_estimate_tables import CONGRESS_API
from spicy_docs.schemas.tables import read_json_column
from spicy_docs.sources.cbo import CboFeedBill
from spicy_docs.sources.congress.bill_cbo_estimates import (
    BillCboShapeError,
    bill_detail_url,
    harvest_bill_cbo_estimates,
    harvest_congress,
    read_bill_cbo_estimates,
    read_bill_detail,
)
from spicy_docs.sources.congress.bill_status import BillIdentity, CboCostEstimate
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
HR2810_BODY = (FIXTURES / "congress-bill-detail-113-hr-2810.json").read_bytes()
S135_BODY = (FIXTURES / "congress-bill-detail-113-s-135.json").read_bytes()
HR2810 = BillIdentity(113, "hr", 2810)
S135 = BillIdentity(113, "s", 135)
KEY = "k3y-abcdef0123456789"
BUDGET = PagedJsonBudget(max_requests=3, max_page_bytes=65536, timeout_seconds=7, min_request_interval_seconds=0)


def record(body: bytes = HR2810_BODY) -> dict:
    """The bill object of a recorded response, as plain JSON to mutate."""
    return json.loads(body)["bill"]


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


# --- the reader ---------------------------------------------------------------------


def test_the_reader_states_each_estimate_verbatim_in_the_billstatus_fields() -> None:
    """pubDate, title, url and description land on the BILLSTATUS route's own fields, the trailing newline kept."""
    reading = read_bill_detail(HR2810_BODY, HR2810)
    assert reading.outcome == "populated"
    assert reading.estimates == (
        CboCostEstimate(
            pub_date="2013-09-13T18:30:00Z",
            title="H.R. 2810, Medicare Patient Access and Quality Improvement Act of 2013",
            url="https://www.cbo.gov/publication/44578",
            description="As ordered reported by the House Committee on Energy and Commerce on July 31, 2013\n",
        ),
        CboCostEstimate(
            pub_date="2014-01-24T16:34:10Z",
            title="H.R. 2810, SGR Repeal and Medicare Beneficiary Access Act of 2013",
            url="https://www.cbo.gov/publication/45040",
            description="As ordered reported by the House Committee on Ways and Means on December 12, 2013\n",
        ),
    )
    assert reading.report_citations == ("H. Rept. 113-257,Part 1", "H. Rept. 113-257,Part 2")


def test_a_record_without_the_list_is_requested_empty_not_absence() -> None:
    """The publisher omits the key when it lists no estimate; that is recorded, and an empty list apart from it."""
    reading = read_bill_detail(S135_BODY, S135)
    assert (reading.outcome, reading.estimates, reading.report_citations) == (
        "requested-empty:absent",
        (),
        ("S. Rept. 113-270",),
    )
    emptied = read_bill_cbo_estimates({**record(), "cboCostEstimates": []}, HR2810)
    assert (emptied.outcome, emptied.estimates) == ("requested-empty:present-and-empty", ())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(cboCostEstimates={"url": "x"}), "cboCostEstimates is not a list"),
        (lambda r: r.update(cboCostEstimates=None), "cboCostEstimates is not a list"),
        (lambda r: r["cboCostEstimates"].append("https://www.cbo.gov/publication/1"), "non-object item"),
        (lambda r: r["cboCostEstimates"][0].update(pdfUrl="x"), "unknown field"),
        (lambda r: r["cboCostEstimates"][0].update(pubDate=None), "non-string field"),
        (lambda r: r["cboCostEstimates"].append({"title": " ", "url": ""}), "empty item"),
        (lambda r: r.update(committeeReports=[{"url": "x"}]), "states no citation"),
        (lambda r: r.update(committeeReports={}), "committeeReports is not a list"),
        (lambda r: r.update(number="2811"), "names another bill"),
        (lambda r: r.update(type="hr"), "names another bill"),
        (lambda r: r.update(congress="113"), "names another bill"),
    ],
)
def test_an_unknown_shape_is_refused_by_name_never_dropped(mutate, message) -> None:
    """Each shape rule refuses on its own, and the message names the shape without copying source text."""
    mutated = record()
    mutate(mutated)
    with pytest.raises(BillCboShapeError, match=message) as raised:
        read_bill_cbo_estimates(mutated, HR2810)
    assert "cbo.gov" not in str(raised.value)


def test_a_response_without_a_bill_object_is_refused() -> None:
    """The retained bytes must carry the bill object the route answers under."""
    with pytest.raises(BillCboShapeError, match="no bill object"):
        read_bill_detail(b'{"request": {}}', HR2810)


# --- the rows -----------------------------------------------------------------------


def test_congress_api_rows_go_through_the_fold_and_the_shaper() -> None:
    """One row per publication, keyed as the BILLSTATUS route keys it, carrying source congress_api and the
    record's own report citations."""
    tables = build_congress_api_cost_estimates(read_bill_detail(HR2810_BODY, HR2810))
    assert tables.refusals == ()
    assert [CBO_COST_ESTIMATES.key(row) for row in tables.cbo_cost_estimates] == [
        ("113-hr-2810", "44578"),
        ("113-hr-2810", "45040"),
    ]
    first = tables.cbo_cost_estimates[0]
    assert CBO_COST_ESTIMATES.checked(first) == first
    assert (first["source"], first["estimate_index"], first["stated_count"], first["restatements_json"]) == (
        CONGRESS_API,
        "0",
        "1",
        "[]",
    )
    assert first["report_citation_count"] == "2"
    assert read_json_column(first["report_citations_json"])[1] == {
        "citation": "H. Rept. 113-257,Part 2",
        "congress": "113",
        "report_type": "hrpt",
        "number": "257",
        "part": "2",
    }


def test_a_restated_publication_folds_and_an_unkeyable_url_is_refused_by_the_publication_rule() -> None:
    """The route's urls meet the same publication-url rule and fold as BILLSTATUS's do."""
    mutated = record()
    first = dict(mutated["cboCostEstimates"][0])
    mutated["cboCostEstimates"] += [
        {**first, "title": "re-spelled"},
        {**first, "url": "https://www.cbo.gov/system/files/2013-09/hr2810.pdf"},
    ]
    tables = build_congress_api_cost_estimates(read_bill_cbo_estimates(mutated, HR2810))
    assert [row["stated_count"] for row in tables.cbo_cost_estimates] == ["2", "1"]
    assert read_json_column(tables.cbo_cost_estimates[0]["restatements_json"]) == [
        {"estimate_index": 2, "title": "re-spelled"}
    ]
    (refusal,) = tables.refusals
    assert refusal.identity == ("113-hr-2810", "3")
    assert refusal.reason.startswith("cbo_publication_url: cost-estimate url is outside the measured")


def test_the_row_builder_takes_only_a_reading() -> None:
    """A bare estimate list has no identity or report list to shape with."""
    with pytest.raises(TypeError):
        build_congress_api_cost_estimates((CboCostEstimate(None, None, None, None),))  # type: ignore[arg-type]


# --- the harvest --------------------------------------------------------------------


class Transport(httpx.MockTransport):
    """Serves each URL's queued responses in order and records every request."""

    def __init__(self, answers: dict[str, list[tuple[int, bytes]]]):
        self.answers = {url: list(queue) for url, queue in answers.items()}
        self.calls: list[httpx.Request] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        status, body = self.answers[str(request.url)].pop(0)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "application/json"})


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_harvest_keys_by_header_retains_bytes_and_resumes_only_what_failed(tmp_path: Path) -> None:
    """One row per bill: the ok row keeps the exact body and keyless locator; a rerun asks only the failed bill."""
    hr, s = CboFeedBill(HR2810, ("44578", "45040")), CboFeedBill(S135, ())
    output = tmp_path / "harvest.jsonl"
    first = Transport({bill_detail_url(HR2810): [(200, HR2810_BODY)], bill_detail_url(S135): [(502, b"")] * 3})
    written = harvest_bill_cbo_estimates([hr, s], output, api_key=KEY, budget=BUDGET, transport=first)
    assert written == {"ok": 1, "failed": 1}
    assert all(call.headers["x-api-key"] == KEY and "api_key" not in str(call.url) for call in first.calls)
    ok, failed = rows(output)
    assert ok["locator"] == "https://api.congress.gov/v3/bill/113/hr/2810?format=json&limit=250"
    assert ok["body"].encode() == HR2810_BODY and ok["feed_publication_ids"] == ["44578", "45040"]
    assert (ok["status"], ok["outcome"], ok["estimate_count"]) == ("ok", "populated", 2)
    assert read_bill_detail(ok["body"].encode(), HR2810) == read_bill_detail(HR2810_BODY, HR2810)
    assert failed["status"] == "failed" and "body" not in failed

    second = Transport({bill_detail_url(S135): [(429, b""), (200, S135_BODY)]})
    assert harvest_bill_cbo_estimates([hr, s], output, api_key=KEY, budget=BUDGET, transport=second) == {"ok": 1}
    assert [str(call.url) for call in second.calls] == [bill_detail_url(S135)] * 2
    assert rows(output)[-1]["outcome"] == "requested-empty:absent"
    assert KEY not in output.read_text()


def test_the_harvest_keeps_a_refused_shape_and_asks_again_on_resume(tmp_path: Path) -> None:
    """A record for another bill is refused with its bytes kept, and it is not a success a resume skips."""
    output = tmp_path / "harvest.jsonl"
    bill = CboFeedBill(S135, ())
    transport = Transport({bill_detail_url(S135): [(200, HR2810_BODY), (200, S135_BODY)]})
    assert harvest_bill_cbo_estimates([bill], output, api_key=KEY, budget=BUDGET, transport=transport) == {"refused": 1}
    (refused,) = rows(output)
    assert refused["error"] == "BillCboShapeError: bill record names another bill than the one requested"
    assert refused["body"].encode() == HR2810_BODY
    assert harvest_bill_cbo_estimates([bill], output, api_key=KEY, budget=BUDGET, transport=transport) == {"ok": 1}


def test_a_credential_refusal_ends_the_harvest_without_a_row(tmp_path: Path) -> None:
    """401/403 is a refused key, not a bill without estimates: the run stops and records nothing for it."""
    output = tmp_path / "harvest.jsonl"
    transport = Transport({bill_detail_url(HR2810): [(403, b'{"error": "API_KEY_INVALID"}')]})
    with pytest.raises(CredentialRefusedError):
        harvest_bill_cbo_estimates(
            [CboFeedBill(HR2810, ()), CboFeedBill(S135, ())], output, api_key=KEY, budget=BUDGET, transport=transport
        )
    assert output.read_text() == ""
    assert len(transport.calls) == 1


def test_a_congress_harvest_asks_only_the_bills_its_feed_names_and_records_the_feed(tmp_path: Path) -> None:
    """The pinned 119th feed excerpt names one bill (its other item is a procedural notice), so exactly one keyed
    request is made, and the row carries the feed's own locator and digest beside the publication that named it.

    The record served here is synthetic, built for S. 4429 because no Congress.gov record of it is retained."""
    feed = (Path(__file__).parent / "fixtures" / "cbo" / "cbo-119congress-cost-estimates.xml").read_bytes()
    feed_url = "https://www.cbo.gov/rss/119congress-cost-estimates.xml"
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(feed), headers={"content-type": "text/xml"})
    )
    estimate = {"pubDate": "2026-09-11T20:47:00Z", "title": "S. 4429", "url": "https://www.cbo.gov/publication/62720"}
    synthetic = json.dumps({"bill": {"congress": 119, "type": "S", "number": "4429", "cboCostEstimates": [estimate]}})
    s4429 = BillIdentity(119, "s", 4429)
    api = Transport({bill_detail_url(s4429): [(200, synthetic.encode())]})
    named, written = harvest_congress(
        119, tmp_path / "h.jsonl", api_key=KEY, budget=BUDGET, feed_transport=feed_transport, transport=api
    )
    assert [(bill.identity, bill.publication_ids) for bill in named.bills] == [(s4429, ("62720",))]
    assert (named.blank, named.refused, written) == (1, (), {"ok": 1})
    assert api.calls[0].headers["x-api-key"] == KEY and len(api.calls) == 1
    (row,) = rows(tmp_path / "h.jsonl")
    assert (row["feed_url"], row["feed_sha256"]) == (feed_url, "sha256:" + hashlib.sha256(feed).hexdigest())
    assert row["feed_publication_ids"] == ["62720"] and row["estimate_count"] == 1
