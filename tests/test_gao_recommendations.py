"""GAO's open-recommendations export is read strictly, keyed on the number GAO states, and retained with a receipt.

The fixture is the 2026-09-28 export cut to 35 of its records, byte for byte, directors' phones as GAO prints them
(``fixtures/gao_recommendations/``).
"""

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.gao_recommendation_tables import (
    GAO_RECOMMENDATIONS,
    KEY_RULE,
    gao_recommendation_id,
    shape_gao_recommendation,
)
from spicy_docs.sources.gao.recommendations import (
    EXPORT_URL,
    GaoRecommendationsAcquirer,
    GaoRecommendationsBudget,
    GaoRecommendationsSourceError,
    GaoRecommendationsUnavailableError,
    fetch_export,
    parse_recommendations_export,
    read_export,
    redact_director_phone,
    stated_number,
)

EXCERPT = (Path(__file__).parent / "fixtures" / "gao_recommendations" / "open-recs-2026-09-28-excerpt.csv").read_bytes()
HEADER_LINE = b'"Publication Name","Publication  Number","Date Publication Issued","Director Name","Director Phone",'
BUDGET = GaoRecommendationsBudget(max_bytes=1024 * 1024, timeout_seconds=9)
CLOCK = datetime(2026, 9, 28, 23, 25, 35, tzinfo=UTC)


def records(body: bytes = EXCERPT) -> list:
    return list(parse_recommendations_export(body).recommendations)


def cells(body: bytes = EXCERPT) -> list[list[str]]:
    """The export's CSV rows as a second reader sees them, preamble and header included."""
    return list(csv.reader(io.StringIO(body.decode(), newline="")))


def test_the_excerpt_reads_every_record_in_export_order_under_the_stamp_gao_states():
    export = parse_recommendations_export(EXCERPT)
    assert export.status_as_of == "Sep 28, 2026 at 7:05 PM EST"
    assert export.as_of == date(2026, 9, 28)
    assert [item.position for item in export.recommendations] == list(range(35))
    first = export.recommendations[0]
    assert first.publication_number == "GAO-26-108061" and first.report_id == "gao-26-108061"
    assert first.publication_title.startswith("Firearms Trafficking to Mexico:")
    assert first.publication_date == date(2026, 9, 28)
    assert first.director_name == "Chelsa L. Kenney"
    assert first.agency == "Department of State"
    assert (first.number_kind, first.number) == ("recommendation", "4")
    assert first.status == "Open" and first.priority is False
    assert first.topics == "International Affairs"


def test_the_last_record_needs_no_terminator():
    last = records()[-1]
    assert last.publication_number == "GAO-02-47T" and last.publication_date == date(2001, 10, 10)
    assert last.topics == "Business Regulation and Consumer Protection"


def test_every_spelling_of_the_stated_number_the_export_uses_is_read():
    """Each variant is a record of the real export; the common spelling covers the other 4,705 numbered records."""
    stated = {item.recommendation[-45:]: (item.number_kind, item.number) for item in records()}
    expected = {
        "(Recommendation 4)": ("recommendation", "4"),
        "(recommendation 1)": ("recommendation", "1"),
        "(Recommendations 5)": ("recommendation", "5"),
        "[Recommendation 1]": ("recommendation", "1"),
        "(Recommendation 1.)": ("recommendation", "1"),
        "(Recommendation 19-01)": ("recommendation", "19-01"),
        "(Recommendation 9": ("recommendation", "9"),
        "(Matter for Consideration 1)": ("matter", "1"),
        "(Matter 4)": ("matter", "4"),
    }
    for ending, value in expected.items():
        assert {kind for text, kind in stated.items() if text.endswith(ending)} == {value}, ending
    unnumbered = [text for text, kind in stated.items() if kind == (None, None)]
    assert len(unnumbered) == 2
    assert any(text.endswith("(Matter for Congressional Consideration)") for text in unnumbered)
    assert stated_number("GAO should act (Matter for Congressional Consideration 2)") == ("matter", "2")
    assert stated_number("It cites 43 C.F.R. 4150.2(a) (2005).") is None
    assert stated_number("(Recommendation 2) comes first here, then more text.") is None


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
    quoted = next(item.recommendation for item in records() if item.publication_number == "GAO-26-108623")
    assert '"' in quoted and '""' not in quoted
    padded = [item.comments for item in records() if item.comments and item.comments != item.comments.strip()]
    assert len(padded) == 2
    text = "".join(item.publication_title + item.recommendation + (item.comments or "") for item in records())
    assert "\u202f" in text and "\u200b" in text


def test_an_escaped_ampersand_is_read_as_the_ampersand_it_spells():
    """The export spells every ampersand ``&amp;`` (637 in the full export, no bare one and no other entity)."""
    assert b"Centers for Medicare &amp; Medicaid Services" in EXCERPT
    agencies = {item.agency for item in records()}
    assert "Centers for Medicare & Medicaid Services" in agencies
    assert not any(
        "&amp;" in value
        for item in records()
        for value in (item.publication_title, item.agency, item.recommendation, item.comments or "")
    )
    assert any("R&D" in item.publication_title for item in records())


@pytest.mark.parametrize(
    ("spelling", "message"),
    [
        (b"&amp;amp;", "doubled"),
        (b"&lt;", "not spelled"),
        (b"& ", "not spelled"),
        (b"&#38;", "not spelled"),
    ],
)
def test_an_ampersand_spelled_any_other_way_refuses(spelling, message):
    body = EXCERPT.replace(
        b"Centers for Medicare &amp; Medicaid", b"Centers for Medicare " + spelling + b" Medicaid", 1
    )
    with pytest.raises(GaoRecommendationsSourceError, match=message):
        parse_recommendations_export(body)


def test_absent_fields_are_absent_and_the_two_statuses_and_priorities_both_read():
    rows = records()
    assert sum(item.director_name is None for item in rows) == 2
    assert sum(item.topics is None for item in rows) == 1
    assert {item.status for item in rows} == {"Open", "Open--Partially Addressed"}
    assert {item.priority for item in rows} == {True, False}
    assert date(2026, 9, 8) in {item.publication_date for item in rows}


def key(item) -> str:
    return gao_recommendation_id(
        item.report_id, item.agency, item.recommendation, kind=item.number_kind, number=item.number
    )


def test_one_recommendation_made_to_three_agencies_is_three_records_with_three_keys():
    rows = [item for item in records() if item.publication_number == "GAO-22-104824"]
    assert len(rows) == 3 and len({item.recommendation for item in rows}) == 1
    assert {(item.number_kind, item.number) for item in rows} == {("recommendation", "1")}
    assert len({key(item) for item in rows}) == 3


def test_a_numbered_key_survives_any_edit_to_the_text_and_is_the_digest_of_the_number():
    """The rule named in the contract: the number where GAO states it, prefixed so it can never equal a text key."""
    first = records()[0]
    number = gao_recommendation_id(
        "gao-26-108061", "Department of State", "Reworded (Recommendation 4)", kind="recommendation", number="4"
    )
    assert number == key(first)
    parts = "number\x1fgao-26-108061\x1frecommendation\x1f4\x1fdepartment of state"
    assert number == "sha256:" + hashlib.sha256(parts.encode()).hexdigest()
    assert KEY_RULE in GAO_RECOMMENDATIONS.descriptions["recommendation_id"]
    assert number != gao_recommendation_id(
        "gao-26-108061", "Department of State", first.recommendation, kind="matter", number="4"
    )


def test_the_key_folds_the_numbers_case_and_the_fields_spacing_and_case():
    text = gao_recommendation_id("gao-26-108061", "Department of State", "Do  the\u202fthing.", kind=None, number=None)
    assert text == gao_recommendation_id(
        "GAO-26-108061", " department of state", "do the THING. ", kind=None, number=None
    )
    assert text != gao_recommendation_id(
        "gao-26-108061", "Department of State", "Do the other thing.", kind=None, number=None
    )
    expected = hashlib.sha256(b"text\x1fgao-26-108061\x1fdepartment of state\x1fdo the thing.").hexdigest()
    assert text == f"sha256:{expected}"
    numbered = gao_recommendation_id("GAO-26-108061", "Department of State", "", kind="recommendation", number="4")
    assert numbered == key(records()[0])


@pytest.mark.parametrize(("kind", "number"), [("recommendation", None), (None, "4"), ("finding", "4")])
def test_a_key_needs_a_known_kind_and_a_number_together(kind, number):
    with pytest.raises(ValueError, match="stated number"):
        gao_recommendation_id("gao-26-108061", "Department of State", "text", kind=kind, number=number)


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
        (EXCERPT.split(HEADER_LINE)[0], "cut"),
    ],
)
def test_a_changed_preamble_or_header_refuses_the_whole_export(body, message):
    with pytest.raises(GaoRecommendationsSourceError, match=message):
        parse_recommendations_export(body)


def _header_end(body: bytes = EXCERPT) -> int:
    return body.index(b"\n", body.index(HEADER_LINE)) + 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        # Cut at a record boundary: the export's last byte is never a line end.
        (EXCERPT[: EXCERPT.rindex(b"\n") + 1], "cut"),
        (EXCERPT + b"\r\n", "cut"),
        # Cut inside the last field: its quote is left open.
        (EXCERPT[:-10], "well-formed"),
        # The header and nothing after it.
        (EXCERPT[: _header_end() - 1], "no record"),
    ],
    ids=["record-boundary", "trailing-crlf", "inside-last-field", "header-only"],
)
def test_a_cut_export_refuses(body, message):
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
        (b'"Department of State","The Secretary of State should', b'"Department of State","', "recommendation"),
    ],
)
def test_a_record_that_breaks_the_exports_rules_refuses_the_whole_export_and_names_its_position(old, new, message):
    body = mutate(old, new)
    if message == "recommendation":
        # Empty the whole text of record 0, not only its opening words.
        start = EXCERPT.index(old) + len(b'"Department of State","')
        end = EXCERPT.index(b'",Open,No,', start)
        body = EXCERPT[:start] + EXCERPT[end:]
    with pytest.raises(GaoRecommendationsSourceError, match=f"{message}.*record 0|record 0.*{message}"):
        parse_recommendations_export(body)


def test_a_record_with_the_wrong_field_count_refuses():
    body = mutate(b',"International Affairs"\n', b',"International Affairs",""\n')
    with pytest.raises(GaoRecommendationsSourceError, match="record 0 has 12 fields"):
        parse_recommendations_export(body)


def test_a_repeated_key_refuses_rather_than_dropping_a_row():
    first_record_end = EXCERPT.index(b'"International Affairs"\n') + len(b'"International Affairs"\n')
    body = EXCERPT[:first_record_end] + EXCERPT[_header_end() :]
    with pytest.raises(GaoRecommendationsSourceError, match="repeats the key of record 0"):
        parse_recommendations_export(body)


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
    assert (first["recommendation_kind"], first["recommendation_number"]) == ("recommendation", "4")
    assert first["first_seen"] == first["last_seen"] == "2026-09-28" and first["listed_open"] == "true"
    assert first["status_as_of"] == "Sep 28, 2026 at 7:05 PM EST" and first["priority"] == "false"
    assert rows[-1]["recommendation_kind"] is None and rows[-1]["recommendation_number"] is None
    assert TABLE_CONTRACTS["gao_recommendations"] is GAO_RECOMMENDATIONS


#: Every value the fixture states in its Director Phone column, as GAO prints it.
PHONES = [row[4] for row in cells()[6:] if row[4]]


def test_the_director_phone_is_neither_read_nor_published():
    """Owner decision, 2026-09-28: the director's name only. The phone stays in the retained bytes alone."""
    assert len(PHONES) == 14 and all(phone.encode() in EXCERPT for phone in PHONES)
    export = parse_recommendations_export(EXCERPT)
    rows = [shape_gao_recommendation(item, status_as_of=export.status_as_of, as_of=export.as_of) for item in records()]
    published = json.dumps(rows) + repr(records())
    assert not any(phone in published for phone in PHONES)
    assert "director_phone" not in GAO_RECOMMENDATIONS.columns


def test_the_redactor_empties_only_the_phone_fields():
    redacted, emptied = redact_director_phone(EXCERPT)
    assert emptied == len(PHONES) and not any(phone.encode() in redacted for phone in PHONES)
    before, after = cells(EXCERPT), cells(redacted)
    assert after[:6] == before[:6]
    assert [row[:4] + row[5:] for row in after[6:]] == [row[:4] + row[5:] for row in before[6:]]
    assert all(row[4] == "" for row in after[6:])
    # Each value goes, with the quotes GAO put round it where it did (not round an unspaced one).
    quoted = [f',"{phone}",'.encode() in EXCERPT for phone in PHONES]
    assert len(EXCERPT) - len(redacted) == sum(len(phone.encode()) + 2 * q for phone, q in zip(PHONES, quoted))
    assert parse_recommendations_export(redacted) == parse_recommendations_export(EXCERPT)


def test_the_redactor_finds_a_moved_phone_column_and_refuses_bytes_without_one():
    moved = EXCERPT.replace(b'"Director Name","Director Phone"', b'"Director Phone","Director Name"', 1)
    redacted, emptied = redact_director_phone(moved)
    # Whatever the header names the phone is what goes: here the fourth column, the fifth kept.
    assert [row[3] for row in cells(redacted)[6:]] == [""] * 35
    assert [row[4] for row in cells(redacted)[6:]] == [row[4] for row in cells(moved)[6:]]
    assert emptied == sum(bool(row[3]) for row in cells(moved)[6:])
    for body in (b'not,a\n"csv', EXCERPT.replace(b'"Director Phone"', b'"Director Contact"')):
        with pytest.raises(GaoRecommendationsSourceError, match="no phone can be found"):
            redact_director_phone(body)


@pytest.mark.parametrize(
    ("old", "new"),
    [(b',"International Affairs"\n', b',"International Affairs",""\n'), (b',"International Affairs"\n', b"\n")],
    ids=["one-field-too-many", "one-field-too-few"],
)
def test_the_redactor_refuses_a_record_whose_width_differs_from_the_headers(old, new):
    """It also runs on refused exports, where the reader's own width refusal never ran: a wrong-width record there
    would blank another field and keep the phone, so it refuses and nothing is retained."""
    with pytest.raises(GaoRecommendationsSourceError, match="the header's 11"):
        redact_director_phone(mutate(old, new))


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
    assert len(export.recommendations) == 35


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


class Proxied:
    """What the receipt reads from the Zyte transport's ``record_for``."""

    proxied_client, mode, zyte_request_id = "zyte", "httpResponseBody", "req-1"


def test_a_fetch_retains_the_bytes_and_a_receipt_that_a_read_verifies(tmp_path):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    looked_up = []
    result = fetch_export(
        store=store,
        receipts=receipts,
        budget=BUDGET,
        transport=Transport(csv_response()),
        proxy_record=lambda url: looked_up.append(url) or Proxied(),
    )
    assert result == 0 and looked_up == [EXPORT_URL]
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["export"]
    receipt = rows[0]
    assert receipt["request_url"] == EXPORT_URL and receipt["content_type"] == "text/csv; charset=UTF-8"
    assert receipt["sha256"] == "sha256:" + hashlib.sha256(EXCERPT).hexdigest() and receipt["bytes"] == len(EXCERPT)
    assert receipt["status_as_of"] == "Sep 28, 2026 at 7:05 PM EST" and receipt["recommendations"] == 35
    assert (receipt["proxied_client"], receipt["zyte_request_id"]) == ("zyte", "req-1")
    export, capture = read_export(receipts=receipts, store=store)
    assert capture.body == EXCERPT and len(export.recommendations) == 35


def test_a_failed_fetch_records_the_refusal_and_keeps_the_refused_bytes(tmp_path):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    changed = mutate(b'"Publication  Number"', b'"Publication Number"')
    assert fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response(changed))) == 1
    (row,) = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert row["kind"] == "failed" and "header" in row["error"]
    assert row["refused_evidence"]["sha256"].endswith(hashlib.sha256(changed).hexdigest())
    with pytest.raises(GaoRecommendationsSourceError, match="no retained export"):
        read_export(receipts=receipts, store=store)


CREDENTIAL = "zyte-secret-credential-value"


def test_a_refusal_quoting_the_credential_across_the_truncation_leaves_no_part_of_it(tmp_path):
    """The error is scrubbed before it is cut to 1,000 characters, or the credential's front would survive the cut."""
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    prefix = "GAO recommendations export header differs from the one measured: [['"
    echoed = mutate(b'"Publication Name"', f'"{"x" * (995 - len(prefix))}{CREDENTIAL}"'.encode())
    result = fetch_export(
        store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response(echoed)), credential=CREDENTIAL
    )
    assert result == 1
    text = receipts.read_text()
    assert CREDENTIAL[:5] not in text and "header" in text
    assert not any(CREDENTIAL.encode() in path.read_bytes() for path in store.rglob("*") if path.is_file())


def test_an_accepted_answer_echoing_the_credential_in_a_header_leaves_no_trace_of_it(tmp_path):
    """Every receipt field passes the row scrub, not only the error: here the media type the publisher stated."""
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    response = csv_response(content_type=f"text/csv; charset=UTF-8; note={CREDENTIAL}")
    result = fetch_export(
        store=store, receipts=receipts, budget=BUDGET, transport=Transport(response), credential=CREDENTIAL
    )
    assert result == 0
    text = receipts.read_text()
    assert CREDENTIAL not in text and '"kind": "export"' in text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda row: {**row, "bytes": row["bytes"] + 1}, "differs from its receipt"),
        (lambda row: {**row, "request_url": "https://www.gao.gov/open-recs2-csv?q=gao"}, "another URL"),
        (lambda row: {**row, "sha256": "sha256:" + "0" * 64}, "sha256/0{64}"),
    ],
    ids=["size", "url", "digest"],
)
def test_a_read_refuses_a_receipt_its_bytes_do_not_match(tmp_path, change, message):
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response()))
    row = json.loads(receipts.read_text())
    receipts.write_text(json.dumps(change(row)) + "\n")
    with pytest.raises(Exception, match=message) as raised:
        read_export(receipts=receipts, store=store)
    assert not isinstance(raised.value, AssertionError)


def test_a_read_refuses_retained_bytes_changed_after_their_receipt(tmp_path):
    """The store proves the receipt's digest on open, so bytes altered in place, same size, never reach the parser."""
    store, receipts = tmp_path / "store", tmp_path / "receipts.jsonl"
    fetch_export(store=store, receipts=receipts, budget=BUDGET, transport=Transport(csv_response()))
    (blob,) = [path for path in store.rglob("*") if path.is_file()]
    blob.chmod(0o644)
    blob.write_bytes(EXCERPT.replace(b"Department of State", b"Department of Stata", 1))
    with pytest.raises(Exception, match="differ from their content address"):
        read_export(receipts=receipts, store=store)
