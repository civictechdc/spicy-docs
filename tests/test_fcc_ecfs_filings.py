"""FCC mirror traversal proves bounded leaves and reconciles inclusive timestamp partitions."""

import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from spicy_docs.reading.paged_json import IncompleteWalkError, PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources import fcc_ecfs_filings as traversal
from spicy_docs.sources.fcc_ecfs import FccEcfsReader, filings_url
from spicy_docs.transport.credentials import CredentialRefusedError

START = datetime(2017, 4, 27, 13, 20, 7, tzinfo=UTC)
BUDGET = PagedJsonBudget(1, 128 * 1024, 5, 0)


def filing(number, *, timestamp=None, received="2017-04-28T00:00:00Z"):
    return {
        "id_submission": str(number),
        "date_submission": timestamp or (START + timedelta(seconds=number)).isoformat(),
        "date_received": received,
        "express_comment": number % 2,
        "proceedings": [{"name": "17-108"}],
    }


def utc(value):
    instant = datetime.fromisoformat(value)
    return instant if instant.tzinfo else instant.replace(tzinfo=UTC)


def payload(rows, count):
    return {
        "filing": rows,
        "aggregations": {
            "express_comment": {
                "doc_count_error_upper_bound": 0,
                "sum_other_doc_count": 0,
                "buckets": [{"key": 1, "doc_count": count}] if count else [],
            }
        },
    }


def response(body):
    return httpx.Response(
        200, stream=httpx.ByteStream(json.dumps(body).encode()), headers={"content-type": "application/json"}
    )


class Publisher(httpx.MockTransport):
    """Inclusive filters, stable counts and real offset semantics; ``ignore`` names filters it drops."""

    def __init__(self, rows, alter=None, *, ignore=()):
        self.rows = rows
        self.alter = alter
        self.ignore = ignore
        self.calls = []
        super().__init__(self.respond)

    def respond(self, request):
        self.calls.append(request)
        query = request.url.params
        rows = sorted(self.rows, key=lambda row: utc(row["date_submission"]), reverse=query["sort"].endswith("DESC"))
        for field, bounds in (
            ("date_submission", query.get("date_submission")),
            ("date_received", query["date_received"]),
        ):
            if bounds and field not in self.ignore:
                low, high = (utc(value) for value in bounds.removeprefix("[gte]").split("[lte]"))
                rows = [row for row in rows if low <= utc(row[field]) <= high]
        if bounds := query.get("date_submission"):
            assert all(re.search(r"\.\d{3}Z$", value) for value in bounds.removeprefix("[gte]").split("[lte]"))
        if (name := query.get("proceedings.name")) and "proceedings.name" not in self.ignore:
            rows = [row for row in rows if {"name": name} in row["proceedings"]]
        offset, limit = int(query["offset"]), int(query["limit"])
        assert offset + limit <= traversal.MAX_RESULT_WINDOW
        body = payload(rows[offset : offset + limit], len(rows))
        if self.alter:
            self.alter(request, body)
        return response(body)


def read(transport, **kwargs):
    with FccEcfsReader(budget=BUDGET, api_key="fixture-key", transport=transport) as reader:
        return list(reader.iter_filings(received_from="2017-04-01", received_to="2017-04-30", **kwargs))


def test_filings_accept_larger_pages_without_changing_proceedings_limit():
    assert "limit=5000" in filings_url(received_from="2017-04-01", received_to="2017-04-30", limit=5000)
    with pytest.raises(PagedJsonSourceError, match="5000"):
        filings_url(received_from="2017-04-01", received_to="2017-04-30", limit=5001)


def test_small_selection_reuses_first_page_and_retains_every_exact_page():
    publisher = Publisher([filing(0), filing(1)])
    pages = []
    assert read(publisher, on_page=pages.append) == publisher.rows
    assert len(publisher.calls) == len(pages) == 1
    assert json.loads(pages[0].capture.body) == payload(publisher.rows, 2)
    assert publisher.calls[0].url.params["limit"] == "1000"
    assert "fixture-key" not in pages[0].capture.requested_url


def test_large_selection_splits_before_deep_offsets_and_deduplicates_midpoints(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    # All filings were received on one day; submission timestamps still divide
    # them. The root midpoint is an actual filing, seen by both closed children.
    publisher = Publisher([filing(i) for i in range(17)])
    pages = []
    rows = read(publisher, limit=3, proceeding="17-108", on_page=pages.append)
    assert rows == publisher.rows
    assert len({row["id_submission"] for row in rows}) == 17
    assert len(pages) == len(publisher.calls)
    assert len(publisher.calls) < 30
    for call in publisher.calls:
        assert call.url.params["proceedings.name"] == "17-108"
        assert call.url.params["date_received"] == "[gte]2017-04-01[lte]2017-05-01"
        assert "fixture-key" not in str(call.url)
    assert int(publisher.calls[1].url.params["limit"]) == 1
    assert publisher.calls[1].url.params["sort"] == "date_submission,DESC"


def test_boundary_identity_disagreement_refuses_even_when_counts_match(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    midpoint = traversal._stamp(START + timedelta(seconds=4))

    def changed_boundary(request, body):
        if request.url.params.get("date_submission", "").startswith(f"[gte]{midpoint}[lte]"):
            body["filing"] = [
                {**row, "id_submission": "replacement"} if row["id_submission"] == "4" else row
                for row in body["filing"]
            ]

    with pytest.raises(PagedJsonSourceError, match="reconcile"):
        read(Publisher([filing(i) for i in range(9)], changed_boundary), limit=3)


def test_reach_is_safe_for_every_retry_page_size(monkeypatch):
    # 100/95/89-row pages reach 1000/950/979 rows. The middle page size,
    # not the smallest one, is the limiting pass.
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 1000)
    publisher = Publisher([filing(i) for i in range(960)])
    assert len(read(publisher, limit=100)) == 960
    assert any("date_submission" in call.url.params for call in publisher.calls)


def test_child_count_loss_refuses_after_partial_iteration(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    midpoint = traversal._stamp(START + timedelta(seconds=4))

    class LosesOneFromTheRightChild(Publisher):
        # A consistent right child: its count and pages agree, but its parent counted one more.
        def respond(self, request):
            if not request.url.params.get("date_submission", "").startswith(f"[gte]{midpoint}"):
                return super().respond(request)
            every, self.rows = self.rows, [row for row in self.rows if row["id_submission"] != "8"]
            try:
                return super().respond(request)
            finally:
                self.rows = every

    yielded = []
    transport = LosesOneFromTheRightChild([filing(i) for i in range(9)])
    with (
        FccEcfsReader(budget=BUDGET, api_key="fixture-key", transport=transport) as reader,
        pytest.raises(PagedJsonSourceError, match="reconcile"),
    ):
        for row in reader.iter_filings(received_from="2017-04-01", received_to="2017-04-30", limit=3):
            yielded.append(row["id_submission"])
    # Both leaves reached the caller before the parent refused: stage outputs until exhaustion.
    assert yielded == [str(i) for i in range(8)]


def test_tied_instant_overflow_refuses_in_bounded_requests(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    publisher = Publisher([filing(i, timestamp=START.isoformat()) for i in range(9)])
    with pytest.raises(PagedJsonSourceError, match="tied timestamp"):
        read(publisher, limit=3)
    assert len(publisher.calls) == 3


def test_adjacent_milliseconds_split_into_two_point_queries(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    rows = [filing(i, timestamp=(START + timedelta(milliseconds=i // 5)).isoformat()) for i in range(9)]
    publisher = Publisher(rows)
    assert read(publisher, limit=3) == rows
    bounds = {call.url.params.get("date_submission") for call in publisher.calls}
    for instant in (START, START + timedelta(milliseconds=1)):
        assert f"[gte]{traversal._stamp(instant)}[lte]{traversal._stamp(instant)}" in bounds


def test_naive_and_offset_timestamps_use_utc_bounds_without_changing_native_rows(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    rows = [filing(i) for i in range(9)]
    rows[0]["date_submission"] = START.replace(tzinfo=None).isoformat()
    rows[-1]["date_submission"] = "2017-04-27T09:20:15-04:00"
    publisher = Publisher(rows)
    assert read(publisher, limit=3) == rows
    for call in publisher.calls:
        if bounds := call.url.params.get("date_submission"):
            assert bounds.endswith("Z") and "Z[lte]" in bounds


def test_partition_bounds_round_outward_if_source_supplies_finer_precision(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    rows = [filing(i, timestamp=(START + timedelta(seconds=i, microseconds=125)).isoformat()) for i in range(9)]
    publisher = Publisher(rows)
    assert read(publisher, limit=3) == rows
    bounds = publisher.calls[2].url.params["date_submission"]
    assert bounds == "[gte]2017-04-27T13:20:07.000Z[lte]2017-04-27T13:20:15.001Z"


@pytest.mark.parametrize(
    "damage", ["missing", "approximate", "negative", "boolean", "uncounted", "duplicate-key", "flag", "false-error"]
)
def test_unusable_count_evidence_refuses(damage):
    def alter(request, body):
        aggregation = body["aggregations"]["express_comment"]
        if damage == "missing":
            del body["aggregations"]
        elif damage == "approximate":
            aggregation["doc_count_error_upper_bound"] = 1
        elif damage == "negative":
            aggregation["buckets"][0]["doc_count"] = -1
        elif damage == "boolean":
            aggregation["buckets"][0]["doc_count"] = True
        elif damage == "duplicate-key":
            aggregation["buckets"].append({"key": 1, "doc_count": 0})
        elif damage == "false-error":
            aggregation["doc_count_error_upper_bound"] = False
        elif damage == "flag":
            body["filing"][0]["express_comment"] = [0, 1]
        else:
            del body["filing"][0]["express_comment"]

    with pytest.raises(PagedJsonSourceError, match="express_comment"):
        read(Publisher([filing(0)], alter))


def test_count_drift_between_pages_refuses():
    def changed(request, body):
        if request.url.params["offset"] != "0":
            body["aggregations"]["express_comment"]["buckets"][0]["doc_count"] += 1

    with pytest.raises(PagedJsonSourceError, match="count changed"):
        read(Publisher([filing(i) for i in range(3)], changed), limit=2)


def test_shifted_walks_pool_ids_and_move_page_boundaries():
    calls = []

    def respond(request):
        calls.append(request)
        row = filing(0 if len(calls) == 1 else 1)
        return response(payload([row, row], 2))

    rows = read(httpx.MockTransport(respond))
    assert [row["id_submission"] for row in rows] == ["0", "1"]
    assert [call.url.params["limit"] for call in calls] == ["1000", "948"]


def test_repeated_incomplete_walks_do_not_settle():
    with pytest.raises(IncompleteWalkError):
        read(httpx.MockTransport(lambda _: response(payload([filing(0), filing(0)], 2))))


def test_missing_id_refuses():
    def alter(request, body):
        body["filing"][0].pop("id_submission")

    with pytest.raises(PagedJsonSourceError, match="identity"):
        read(Publisher([filing(0)], alter))


def test_missing_submission_bound_refuses(monkeypatch):
    monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)

    def alter(request, body):
        for row in body["filing"]:
            row.pop("date_submission", None)

    with pytest.raises(PagedJsonSourceError, match="date_submission"):
        read(Publisher([filing(i) for i in range(9)], alter), limit=3)


@pytest.mark.parametrize("crowded", [False, True])
@pytest.mark.parametrize(
    "ignored,stray,message",
    [
        ("date_received", {"date_received": "2017-05-01T00:00:00.001Z"}, "received outside"),
        ("proceedings.name", {"proceedings": [{"name": "17-109"}]}, "outside proceeding 17-108"),
    ],
)
def test_a_filter_the_publisher_ignored_refuses_on_either_path(monkeypatch, crowded, ignored, stray, message):
    # An ignored filter and one that matched nothing look the same; the counts agree with either.
    if crowded:
        monkeypatch.setattr(traversal, "MAX_RESULT_WINDOW", 8)
    rows = [filing(i) for i in range(17 if crowded else 2)]
    rows[-1] = {**rows[-1], **stray}
    kwargs = {"proceeding": "17-108", "limit": 3 if crowded else 1000}
    assert read(Publisher(rows), **kwargs) == rows[:-1]
    with pytest.raises(PagedJsonSourceError, match=message):
        read(Publisher(rows, ignore={ignored}), **kwargs)


def test_the_following_midnight_is_inside_the_closed_received_bound():
    row = filing(0, received="2017-05-01T00:00:00Z")
    assert read(Publisher([row])) == [row]


def test_empty_selection_is_a_successful_observation():
    assert read(Publisher([])) == []


def test_credential_refusal_is_not_an_empty_selection():
    with pytest.raises(CredentialRefusedError):
        read(httpx.MockTransport(lambda _: httpx.Response(403, text="Forbidden")))
