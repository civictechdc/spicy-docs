"""GAO's open-recommendations export is read strictly, keyed on its own fields, and retained with a receipt.

The fixture is the 2026-09-28 export cut to 26 of its records, byte for byte (``fixtures/gao_recommendations/``).
"""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.gao_recommendation_tables import (
    GAO_RECOMMENDATIONS,
    gao_recommendation_id,
    shape_gao_recommendation,
)
from spicy_docs.sources.gao.recommendations import (
    EXPORT_URL,
    HEADER,
    GaoRecommendationsAcquirer,
    GaoRecommendationsBudget,
    GaoRecommendationsSourceError,
    GaoRecommendationsUnavailableError,
    fetch_export,
    parse_recommendations_export,
    read_export,
)

EXCERPT = (Path(__file__).parent / "fixtures" / "gao_recommendations" / "open-recs-2026-09-28-excerpt.csv").read_bytes()
HEADER_LINE = b'"Publication Name","Publication  Number","Date Publication Issued","Director Name","Director Phone",'
BUDGET = GaoRecommendationsBudget(max_bytes=1024 * 1024, timeout_seconds=9)
CLOCK = datetime(2026, 9, 28, 23, 25, 35, tzinfo=UTC)


def records(body: bytes = EXCERPT) -> list:
    return list(parse_recommendations_export(body).recommendations)


def by_position(position: int):
    return next(item for item in records() if item.position == position)


def test_the_excerpt_reads_every_record_in_export_order_under_the_stamp_gao_states():
    export = parse_recommendations_export(EXCERPT)
    assert export.status_as_of == "Sep 28, 2026 at 7:05 PM EST"
    assert export.as_of == date(2026, 9, 28)
    assert [item.position for item in export.recommendations] == list(range(26))
    first = export.recommendations[0]
    assert first.publication_number == "GAO-26-108061" and first.report_id == "gao-26-108061"
    assert first.publication_title.startswith("Firearms Trafficking to Mexico:")
    assert first.publication_date == date(2026, 9, 28)
    assert first.director_name == "Chelsa L. Kenney"
    assert first.agency == "Department of State"
    assert first.status == "Open" and first.priority is False
    assert first.topics == "International Affairs"


def test_the_last_record_needs_no_terminator():
    last = records()[-1]
    assert last.publication_number == "GAO-02-47T" and last.publication_date == date(2001, 10, 10)
    assert last.topics == "Business Regulation and Consumer Protection"


def test_fields_keep_what_gao_wrote_inside_their_quotes():
    """A line break in a title, doubled quotes, outer whitespace and unusual spaces are GAO's text, kept whole."""
    titles = [item.publication_title for item in records() if "\n" in item.publication_title]
    assert titles == [
        (
            "National Nuclear Security Administration: \nAdditional Steps Needed to Improve Cost Estimates for Fixed "
            "Price Subcontracts"
        ),
        "Cybersecurity: \nNetwork Monitoring Program Needs Further Guidance and Actions",
        "Cybersecurity: \nNetwork Monitoring Program Needs Further Guidance and Actions",
    ]
    quoted = records()[3].recommendation
    assert '"' in quoted and '""' not in quoted
    padded = [item.comments for item in records() if item.comments and item.comments != item.comments.strip()]
    assert len(padded) == 2
    text = "".join(item.publication_title + item.recommendation + (item.comments or "") for item in records())
    assert "\u202f" in text and "\u200b" in text


def test_an_escaped_ampersand_is_read_as_the_ampersand_it_spells():
    """The export spells every ampersand ``&amp;`` (637 in the full export, no bare one), so each field is unescaped."""
    assert b"Centers for Medicare &amp; Medicaid Services" in EXCERPT
    agencies = {item.agency for item in records()}
    assert "Centers for Medicare & Medicaid Services" in agencies
    assert not any(
        "&amp;" in value
        for item in records()
        for value in (item.publication_title, item.agency, item.recommendation, item.comments or "")
    )
    assert any("R&D" in item.publication_title for item in records())


def test_absent_fields_are_absent_and_the_two_statuses_and_priorities_both_read():
    rows = records()
    assert sum(item.director_name is None for item in rows) == 2
    assert sum(item.topics is None for item in rows) == 1
    assert {item.status for item in rows} == {"Open", "Open--Partially Addressed"}
    assert {item.priority for item in rows} == {True, False}
    assert date(2026, 9, 8) in {item.publication_date for item in rows}


def test_one_recommendation_made_to_three_agencies_is_three_records_with_three_keys():
    rows = [item for item in records() if item.publication_number == "GAO-22-104824"]
    assert len(rows) == 3 and len({item.recommendation for item in rows}) == 1
    assert len({gao_recommendation_id(item.report_id, item.agency, item.recommendation) for item in rows}) == 3


def vars_of(item) -> list:
    return [getattr(item, name) for name in item.__slots__]


def mutate(old: bytes, new: bytes, body: bytes = EXCERPT) -> bytes:
    assert old in body
    return body.replace(old, new, 1)


@pytest.mark.parametrize(
    "body,message",
    [
        (mutate(b'"Publication  Number"', b'"Publication Number"'), "header"),
        (mutate(b",Topics\n", b",Topics,Extra\n"), "header"),
        (mutate(b"Agency,Recommendation", b"Recommendation,Agency"), "header"),
        (mutate(b"Title: Download of GAO Recommendation Results", b"Title: Something Else"), "preamble"),
        (mutate(b"Prepared by: GAO", b"Prepared by: Someone"), "preamble"),
        (mutate(b"status as of Sep 28, 2026 at 7:05 PM EST", b"status as of yesterday"), "status as of"),
        (
            mutate(b"status as of Sep 28, 2026 at 7:05 PM EST", b"status as of Sep 28, 2026 at 7:05 PM PST"),
            "status as of",
        ),
        (mutate(b'EST" ,,,,,,,\r\n', b'EST" ,,,,,,,\r\nunexpected,,\r\n'), "preamble"),
        (EXCERPT.split(HEADER_LINE)[0], "header"),
    ],
)
def test_a_changed_preamble_or_header_refuses_the_whole_export(body, message):
    with pytest.raises(GaoRecommendationsSourceError, match=message):
        parse_recommendations_export(body)


@pytest.mark.parametrize(
    "old,new,message",
    [
        (b",Open,No,", b",Closed--Implemented,No,", "status"),
        (b",Open,No,", b",Open,Maybe,", "priority"),
        (b',GAO-26-108061,"Sep 28, 2026"', b',GAO-26-108061,"2026-09-28"', "issue date"),
        (b',GAO-26-108061,"Sep 28, 2026"', b',GAO-26-108061,"Feb 30, 2026"', "issue date"),
        (b',GAO-26-108061,"Sep 28, 2026"', b',"","Sep 28, 2026"', "publication number"),
        (b',GAO-26-108061,"Sep 28, 2026"', b',"GAO 26 108061","Sep 28, 2026"', "publication number"),
        (b'"Chelsa L. Kenney",,"Department of State"', b'"Chelsa L. Kenney",,""', "agency"),
    ],
)
def test_a_record_that_breaks_the_exports_rules_refuses_the_whole_export_and_names_its_position(old, new, message):
    with pytest.raises(GaoRecommendationsSourceError, match=f"{message}.*record 0|record 0.*{message}"):
        parse_recommendations_export(mutate(old, new))


def test_a_record_with_the_wrong_field_count_refuses():
    body = mutate(b',"International Affairs"\n', b',"International Affairs",""\n')
    with pytest.raises(GaoRecommendationsSourceError, match="record 0 has 12 fields"):
        parse_recommendations_export(body)


def test_a_repeated_key_refuses_rather_than_dropping_a_row():
    header_end = EXCERPT.index(HEADER_LINE)
    header_end = EXCERPT.index(b"\n", header_end) + 1
    first_record_end = EXCERPT.index(b'"International Affairs"\n', header_end) + len(b'"International Affairs"\n')
    body = EXCERPT[:first_record_end] + EXCERPT[header_end:]
    with pytest.raises(GaoRecommendationsSourceError, match="repeats the key of record 0"):
        parse_recommendations_export(body)


def test_the_key_folds_whitespace_and_case_of_the_number_but_nothing_else():
    key = gao_recommendation_id("gao-26-108061", "Department of State", "Do  the\u202fthing.")
    assert key == gao_recommendation_id("gao-26-108061", " Department of State", "Do the thing. ")
    assert key != gao_recommendation_id("gao-26-108061", "Department of State", "Do the Thing.")
    expected = hashlib.sha256(b"gao-26-108061\x1fDepartment of State\x1fDo the thing.").hexdigest()
    assert key == f"sha256:{expected}"


@pytest.mark.parametrize(
    "body,message",
    [
        (b"", "empty"),
        (EXCERPT.replace(b"Department of State", b"Department of St\xe9te", 1), "UTF-8"),
        (mutate(b'"Firearms Trafficking', b'"Firearms "Trafficking'), "CSV"),
    ],
)
def test_bytes_that_are_not_the_export_refuse(body, message):
    with pytest.raises(GaoRecommendationsSourceError, match=message):
        parse_recommendations_export(body)


def test_an_export_over_its_byte_bound_refuses():
    with pytest.raises(GaoRecommendationsSourceError, match="bound"):
        parse_recommendations_export(EXCERPT, max_bytes=len(EXCERPT) - 1)


def test_shaped_rows_satisfy_the_contract_and_key_uniquely():
    export = parse_recommendations_export(EXCERPT)
    rows = [
        shape_gao_recommendation(item, status_as_of=export.status_as_of, as_of=export.as_of)
        for item in export.recommendations
    ]
    assert all(GAO_RECOMMENDATIONS.checked(row) is row for row in rows)
    assert len({GAO_RECOMMENDATIONS.key(row) for row in rows}) == len(rows)
    first = rows[0]
    assert first["report_id"] == "gao-26-108061" and first["publication_date"] == "2026-09-28"
    assert first["first_seen"] == first["last_seen"] == "2026-09-28" and first["listed_open"] == "true"
    assert first["status_as_of"] == "Sep 28, 2026 at 7:05 PM EST" and first["priority"] == "false"
    assert TABLE_CONTRACTS["gao_recommendations"] is GAO_RECOMMENDATIONS


def test_the_director_phone_is_neither_read_nor_published():
    """Owner decision, 2026-09-28: the director's name only. The phone stays in the retained bytes alone."""
    assert b"(202)512-7952" in EXCERPT
    assert not any("512-7952" in str(value) for item in records() for value in vars_of(item))
    assert "director_phone" not in GAO_RECOMMENDATIONS.columns
    assert "director_name" in GAO_RECOMMENDATIONS.columns


def csv_response(body: bytes = EXCERPT, status: int = 200, content_type: str = "text/csv; charset=UTF-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls: list[httpx.Request] = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def test_the_acquirer_makes_one_request_to_the_export_and_returns_its_exact_bytes():
    transport = Transport(csv_response())
    with GaoRecommendationsAcquirer(budget=BUDGET, transport=transport, clock=lambda: CLOCK) as acquirer:
        export, capture = acquirer.acquire_export()
    assert [str(call.url) for call in transport.calls] == [EXPORT_URL]
    assert capture.body == EXCERPT and capture.sha256 == "sha256:" + hashlib.sha256(EXCERPT).hexdigest()
    assert capture.observed_at.startswith("2026-09-28T23:25:35")
    assert len(export.recommendations) == 26


@pytest.mark.parametrize(
    "response,error",
    [
        (csv_response(b"<html>challenge</html>", content_type="text/html"), GaoRecommendationsSourceError),
        (csv_response(b"not here", status=404, content_type="text/html"), GaoRecommendationsUnavailableError),
        (csv_response(mutate(b'"Publication  Number"', b'"Publication Number"')), GaoRecommendationsSourceError),
    ],
)
def test_a_refused_answer_carries_its_capture(response, error):
    with (
        GaoRecommendationsAcquirer(budget=BUDGET, transport=Transport(response)) as acquirer,
        pytest.raises(error) as raised,
    ):
        acquirer.acquire_export()
    assert raised.value.__dict__["gao_recommendations_acquisition"]["url"] == EXPORT_URL


def test_a_fetch_retains_the_bytes_and_a_receipt_that_a_read_verifies(tmp_path):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    assert fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response())) == 0
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["export"]
    receipt = rows[0]
    assert receipt["request_url"] == EXPORT_URL and receipt["content_type"] == "text/csv; charset=UTF-8"
    assert receipt["sha256"] == "sha256:" + hashlib.sha256(EXCERPT).hexdigest() and receipt["bytes"] == len(EXCERPT)
    assert receipt["status_as_of"] == "Sep 28, 2026 at 7:05 PM EST" and receipt["recommendations"] == 26
    export, capture = read_export(receipts=receipts, store=store)
    assert capture.body == EXCERPT and len(export.recommendations) == 26


def test_a_failed_fetch_records_the_refusal_and_keeps_the_refused_bytes(tmp_path):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    changed = mutate(b'"Publication  Number"', b'"Publication Number"')
    assert fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response(changed))) == 1
    (row,) = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert row["kind"] == "failed" and "header" in row["error"]
    assert row["refused_evidence"]["sha256"].endswith(hashlib.sha256(changed).hexdigest())
    with pytest.raises(GaoRecommendationsSourceError, match="no retained export"):
        read_export(receipts=receipts, store=store)


def test_a_read_refuses_bytes_that_differ_from_their_receipt(tmp_path):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response()))
    row = json.loads(receipts.read_text())
    receipts.write_text(json.dumps({**row, "bytes": row["bytes"] + 1}) + "\n")
    with pytest.raises(GaoRecommendationsSourceError, match="differs from its receipt"):
        read_export(receipts=receipts, store=store)


def test_the_header_is_the_one_measured():
    assert HEADER == (
        "Publication Name",
        "Publication  Number",
        "Date Publication Issued",
        "Director Name",
        "Director Phone",
        "Agency",
        "Recommendation",
        "Status",
        "Priority",
        "Comments",
        "Topics",
    )
