"""SEC probe receipts survive failures, requests go through the SEC acquirer, and trimming keeps the parser's statements."""

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.sec_comments.pages import SecCommentsSourceError, parse_rule_page
from tools.analysis import sec_comments_rule_page_probe as tool

FIXTURES = Path(__file__).parent / "fixtures" / "sec_comments"
RULE = (FIXTURES / "rule-page.html").read_bytes()
#: The complete retained S7-11-23 rule-page response ``rule-page.html`` was trimmed from (README).
FULL_RULE = (FIXTURES / "rule-page-full.html").read_bytes()
INDEX = (FIXTURES / "rulemaking-index.html").read_bytes()


def test_the_retained_full_capture_trims_to_the_pinned_fixture_and_parses_the_same(tmp_path):
    captured, fixture = tmp_path / "capture.html", tmp_path / "fixture.html"
    captured.write_bytes(FULL_RULE)
    tool._emit_fixture(captured, fixture)
    assert fixture.read_bytes() == RULE and len(RULE) < len(FULL_RULE)
    assert parse_rule_page(FULL_RULE, url=tool.S7_RULE_PAGE) == parse_rule_page(RULE, url=tool.S7_RULE_PAGE)
    text = FULL_RULE.decode()
    assert all(text[start:end].encode() in RULE for start, end in tool._node_spans(text))


@pytest.mark.parametrize("name", ["rule-page-slug.html", "rule-page-no-listing.html"])
def test_trim_preserves_the_observed_slug_page_shapes(tmp_path, name):
    body = (FIXTURES / name).read_bytes()
    captured, fixture = tmp_path / "capture.html", tmp_path / "fixture.html"
    captured.write_bytes(body)
    tool._emit_fixture(captured, fixture)
    assert parse_rule_page(fixture.read_bytes(), url=tool.S7_RULE_PAGE) == parse_rule_page(body, url=tool.S7_RULE_PAGE)


@pytest.fixture
def probe(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "BUDGET", dataclasses.replace(tool.BUDGET, min_request_interval_seconds=0))
    monkeypatch.setattr(sys, "argv", ["sec_comments_rule_page_probe", "--out", str(tmp_path)])
    return tmp_path


def serve(answers):
    """A transport answering each request with the next body (or raising it), recording every request."""
    calls, queued = [], iter(answers)

    def handle(request):
        calls.append(request)
        answer = next(queued)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(
            200, stream=httpx.ByteStream(answer), headers={"content-type": "text/html; charset=utf-8"}
        )

    return calls, httpx.MockTransport(handle)


def test_probe_records_exact_body_digests_through_the_declared_agent(probe):
    calls, transport = serve([RULE, INDEX])
    tool.main(transport)
    record = json.loads((probe / "probe-record.json").read_text())
    assert [str(call.url) for call in calls] == [tool.S7_RULE_PAGE, tool.INDEX_URL]
    assert all(call.headers["user-agent"].startswith("spicy-docs-sec-comments/1.0") for call in calls)
    assert [entry["sha256"] for entry in record["requests"]] == [hashlib.sha256(b).hexdigest() for b in (RULE, INDEX)]
    assert (probe / "rules-regulations_2025_06_s7-11-23.html").read_bytes() == RULE
    assert record["outcome"] == "complete" and record["sroRulePage"] is None


def test_probe_follows_the_sro_url_stated_by_the_index(probe):
    index = INDEX.replace(b"S7-11-23", b"SR-NYSE-2026-1").replace(
        b"/rules-regulations/2025/06/s7-11-23", b"/rules-regulations/2026/09/sr-nyse-2026-1"
    )
    calls, transport = serve([RULE, index, RULE])
    tool.main(transport)
    sro_url = f"{tool.SEC_SITE}/rules-regulations/2026/09/sr-nyse-2026-1"
    record = json.loads((probe / "probe-record.json").read_text())
    assert [str(call.url) for call in calls] == [tool.S7_RULE_PAGE, tool.INDEX_URL, sro_url]
    assert record["sroRulePage"] == sro_url and record["outcome"] == "complete"
    assert len(record["requests"]) == 3


@pytest.mark.parametrize("second", [httpx.ConnectError("offline failure"), b"<html>unrecognized index</html>"])
def test_probe_keeps_the_partial_receipt_when_a_later_fetch_or_parse_fails(probe, second):
    calls, transport = serve([RULE, second])
    with pytest.raises((ConnectionError, SecCommentsSourceError)):
        tool.main(transport)
    record = json.loads((probe / "probe-record.json").read_text())
    assert record["requests"][0]["sha256"] == hashlib.sha256(RULE).hexdigest()
    assert record["outcome"] == "failed" and len(calls) == 2  # one attempt per page, no retry
    if isinstance(second, bytes):
        assert record["refused"]["sha256"] == hashlib.sha256(second).hexdigest()


def test_retrimming_a_retained_capture_spends_no_requests(probe, monkeypatch):
    (probe / "rules-regulations_2025_06_s7-11-23.html").write_bytes(FULL_RULE)
    fixture = probe / "fixture.html"
    monkeypatch.setattr(sys, "argv", ["probe", "--out", str(probe), "--emit-fixture", str(fixture)])
    monkeypatch.setattr(tool, "SecCommentsAcquirer", lambda **_: pytest.fail("retrimming made a network request"))
    tool.main()
    assert fixture.read_bytes() == RULE
