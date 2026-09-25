"""Date/class discovery retains native vocabulary and proves a complete, replayable walk."""

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.paged_json import DeclaredCountChanged, DeclaredCountMismatch, PagedJsonBudget
from spicy_docs.sources.ferc.elibrary import (
    CLASS_TYPES_URL,
    FercElibraryAccessRefusedError,
    FercElibraryError,
    FercElibraryReader,
    docket_search_body,
    search_body,
)
from spicy_docs.transport.captured import attached_capture
from tools.analysis.ferc_search_capture import capture_search, main, replay_search

FIXTURES = Path(__file__).parent / "fixtures" / "ferc"
VOCABULARY = (FIXTURES / "class-types-discovery.json").read_bytes()
REQUEST = json.loads((FIXTURES / "advanced-search-all-dockets-request.json").read_bytes())
BUDGET = PagedJsonBudget(8, 256 * 1024, 7, 0)


def transport(*payloads, status=200, content_type="application/json"):
    bodies = iter(payloads)
    return httpx.MockTransport(
        lambda _: httpx.Response(status, stream=httpx.ByteStream(next(bodies)), headers={"content-type": content_type})
    )


def page(references, total, token=None):
    return json.dumps(
        {
            "success": True,
            "totalHits": total,
            "numHits": len(references),
            "searchResultId": token,
            "searchHits": [{"reference": ref, "docketNumbers": ["RM24-5", "ER26-1"]} for ref in references],
        }
    ).encode()


def test_general_builder_matches_browser_scope_and_preserves_all_selector():
    expected = {**REQUEST, "curPage": 1}
    actual = search_body(
        document_class=(("Approved Designation", "All"), ("Application/Petition/Request", "All")),
        date_from="2026-07-27",
        date_to="2026-09-25",
        idol_result_id="",
    )
    assert actual == expected
    assert search_body(document_class=(("Future Class", "Future Type"),))["classTypes"] == [
        {"documentClass": "Future Class", "documentType": "Future Type"}
    ]
    for bad in ("", None, "invalid"):
        with pytest.raises(FercElibraryError):
            docket_search_body(bad)
    assert search_body(docket="rm24-5") == docket_search_body("RM24-5")


def test_live_vocabulary_keeps_duplicate_pairs_unknown_values_and_exact_bytes():
    rows = json.loads(VOCABULARY)
    rows.append({"Class": "Future", "Type": "Unknown", "Library": "X", "Category": "New", "extra": [1]})
    payload = json.dumps(rows).encode()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(payload), headers={"content-type": "application/json"})

    with FercElibraryReader(budget=BUDGET, transport=httpx.MockTransport(respond)) as reader:
        result = reader.class_types()
    assert result.capture.body == payload and result.records == tuple(rows)
    assert result.capture.sha256 == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert str(requests[0].url) == CLASS_TYPES_URL
    assert requests[0].headers["x-applicationid"]
    assert len([row for row in result.records if row["Type"] == "Agenda Materials"]) == 2


@pytest.mark.parametrize("payload", [b"{}", b"null", b"[4]", b'[{"Class":"Comments/Protest"}]'])
def test_vocabulary_rejects_malformed_answers_with_their_evidence(payload):
    with (
        FercElibraryReader(budget=BUDGET, transport=transport(payload)) as reader,
        pytest.raises(FercElibraryError) as refused,
    ):
        reader.class_types()
    assert attached_capture(refused.value).body == payload


@pytest.mark.parametrize("status", [401, 403])
def test_vocabulary_access_refusal_aborts(status):
    with (
        FercElibraryReader(budget=BUDGET, transport=transport(b"{}", status=status)) as reader,
        pytest.raises(FercElibraryAccessRefusedError),
    ):
        reader.class_types()


def test_capture_replays_every_page_and_scope_and_keeps_vocabulary_differences(tmp_path):
    output = tmp_path / "run"
    body = {**REQUEST, "resultsPerPage": 2}
    original = copy.deepcopy(body)
    # A full last page requires a terminal empty page; tokens and the blank
    # docket must survive both continuations and the offline replay.
    with FercElibraryReader(
        budget=BUDGET,
        transport=transport(VOCABULARY, page(["a", "b"], 4, "token"), page(["c", "d"], 4), page([], 4)),
    ) as reader:
        report = capture_search(reader, body, output)
    assert body == original
    assert report["outcome"] == "complete"
    assert report["retained_response_count"] == 4
    assert (report["page_count"], report["distinct_reference_count"], report["declared_count"]) == (3, 4, 4)
    assert ("Application/Petition/Request", "30-Day Advance Notification") in report["vocabulary"]["api_only_pairs"]
    requests = [json.loads((output / item["request_body_path"]).read_bytes()) for item in report["captures"][1:]]
    assert [item["curPage"] for item in requests] == [1, 2, 3]
    assert [item["idolResultID"] for item in requests] == ["", "token", "token"]
    assert all(item["docketSearches"] == body["docketSearches"] for item in requests)
    assert replay_search(output)["outcome"] == "complete"
    with FercElibraryReader(budget=BUDGET, transport=transport()) as reader:
        with pytest.raises(FileExistsError):
            capture_search(reader, body, output)
        assert reader.request_count == 0


@pytest.mark.parametrize(
    ("answers", "error"),
    [
        ([page(["a", "b"], 3), page(["c"], 4)], DeclaredCountChanged),
        ([page(["a", "b"], 4), page(["c"], 4)], DeclaredCountMismatch),
        ([page(["a", "b"], 3), page(["a"], 3)], FercElibraryError),
        ([page(["a", "b"], 3)], FercElibraryError),
    ],
)
def test_failed_walk_keeps_evidence_and_cannot_replay_as_complete(tmp_path, answers, error):
    output = tmp_path / "run"
    with (
        FercElibraryReader(budget=BUDGET, transport=transport(VOCABULARY, *answers)) as reader,
        pytest.raises(error),
    ):
        capture_search(reader, {**REQUEST, "resultsPerPage": 2}, output, max_pages=len(answers))
    report = json.loads((output / "summary.json").read_bytes())
    assert report["outcome"] == "incomplete" and report["error"]
    assert (output / "page-0001.body").read_bytes() == answers[0]
    if error is DeclaredCountChanged:
        assert (output / "refused.body").read_bytes() == answers[-1]
    with pytest.raises(ValueError, match="incomplete"):
        replay_search(output)


def test_empty_answers_remain_observations(tmp_path):
    with FercElibraryReader(budget=BUDGET, transport=transport(b"[]", page([], 0))) as reader:
        report = capture_search(reader, REQUEST, tmp_path / "run")
    assert report["outcome"] == report["vocabulary"]["outcome"] == "requested-empty"
    assert replay_search(tmp_path / "run")["outcome"] == "requested-empty"


def test_capture_keeps_public_access_refusal_evidence(tmp_path):
    output = tmp_path / "run"
    payload = b"publisher refused this public route"
    with (
        FercElibraryReader(budget=BUDGET, transport=transport(payload, status=403)) as reader,
        pytest.raises(FercElibraryAccessRefusedError),
    ):
        capture_search(reader, REQUEST, output)
    report = json.loads((output / "summary.json").read_bytes())
    assert report["outcome"] == "incomplete"
    assert report["retained_response_count"] == 1
    assert report["refusal"]["sha256"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert report["refusal"]["unavailable_reason"] == "access-refused"


@pytest.mark.parametrize("mutation", ["bytes", "scope", "count", "response-count", "extra-page"])
def test_replay_rejects_damaged_evidence_and_false_summary(tmp_path, mutation):
    output = tmp_path / "run"
    with FercElibraryReader(budget=BUDGET, transport=transport(VOCABULARY, page(["a"], 1))) as reader:
        capture_search(reader, REQUEST, output)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_bytes())
    if mutation == "bytes":
        (output / "page-0001.body").write_bytes(b"changed")
    elif mutation == "scope":
        payload = json.dumps({**REQUEST, "classTypes": []}).encode()
        (output / "request.json").write_bytes(payload)
        summary["request_sha256"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    elif mutation == "count":
        summary["distinct_reference_count"] = 2
    elif mutation == "response-count":
        summary["retained_response_count"] = 1
    else:
        summary["captures"].append(summary["captures"][-1])
        summary["retained_response_count"] += 1
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        replay_search(output)


def test_replay_bounds_pages_by_the_retained_responses_not_a_fixed_pin(tmp_path):
    """A page larger than the live CLI's 4 MiB default still replays: the bound comes from the retained bytes."""
    output = tmp_path / "run"
    large = json.dumps(
        {
            "success": True,
            "totalHits": 1,
            "numHits": 1,
            "searchResultId": None,
            "searchHits": [{"reference": "a", "description": "x" * (5 * 1024**2)}],
        }
    ).encode()
    budget = PagedJsonBudget(8, 8 * 1024**2, 7, 0)
    with FercElibraryReader(budget=budget, transport=transport(VOCABULARY, large)) as reader:
        capture_search(reader, REQUEST, output)
    assert replay_search(output)["outcome"] == "complete"


def test_the_cli_reports_an_unreadable_summary_instead_of_a_traceback(tmp_path, capsys):
    (tmp_path / "summary.json").write_text("{}")
    assert main(["--replay", str(tmp_path)]) == 1
    assert "KeyError" in capsys.readouterr().err
