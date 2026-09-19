"""OLRC classification tables prove their own Congress, session and rows.

The fixtures are bounded cuts of the 2026-09-19 captures in
`corpora/supply-2026-09-02/receipts/olrc-classification-2026-09-19/`: the
whole index minus its site menu, and the 2nd-session table's column header
plus nine of its 583 data lines, chosen to reach a quoted new-section act
section, a page span with no statviewer link and a bare ``nt`` row. What the
fixture run proves is the readers' refusals and the shape of one row; the
whole-page facts (583 rows in both orders, same multiset, 38 stated laws) are
receipted in that directory's ``parse_check.out``, which ran the same readers
over both full pages.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.uscode import UsCodeSourceError
from spicy_docs.sources.uscode.acquisition import UsCodeAcquirer, UsCodeAcquisitionBudget
from spicy_docs.sources.uscode.classification import (
    CLASSIFICATION_INDEX_URL,
    INDEX_TITLE,
    classification_table_file_name,
    classification_table_locator,
    parse_classification_index,
    parse_classification_table,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"
INDEX = (FIXTURES / "classification-tables-index.shtml").read_bytes()
TABLE = (FIXTURES / "classification-tbl119pl_2nd-head.htm").read_bytes()
BUDGET = UsCodeAcquisitionBudget(2, 1 << 20, 7, 0)


def cut_pre_block(body: bytes, *kept_lines: bytes) -> bytes:
    """Replace the page's ``<PRE>`` payload with the given lines."""
    start = body.index(b"<PRE>") + len(b"<PRE>")
    end = body.index(b"</pre>")
    lines = body[start:end].split(b"\n")
    header = next(line for line in lines if b"Title" in line and b"Stat." in line)
    return body[:start] + b"\n".join((header,) + kept_lines) + b"\n" + body[end:]


def test_the_index_lists_the_current_congress_tables_in_page_order():
    index = parse_classification_index(INDEX)
    assert index.title == INDEX_TITLE
    assert index.identity_basis == ("title:native",)
    assert [(link.congress, link.session, link.order) for link in index.tables] == [
        (119, 2, "public-law"),
        (119, 2, "code"),
        (119, 1, "public-law"),
        (119, 1, "code"),
    ]
    assert index.tables[0].url == "https://uscode.house.gov/classification/tbl119pl_2nd.htm"


def test_a_page_that_is_not_the_index_is_refused_rather_than_read_as_table_free():
    challenge = b"<html><head><title>Access Denied</title></head><body></body></html>"
    with pytest.raises(UsCodeSourceError, match="does not state the expected title"):
        parse_classification_index(challenge)


def test_an_index_with_the_right_title_but_no_tables_is_refused():
    bare = b"<html><head><title>UNITED STATES CODE CLASSIFICATION TABLES</title></head><body></body></html>"
    with pytest.raises(UsCodeSourceError, match="links no session tables"):
        parse_classification_index(bare)


def test_the_table_file_name_is_the_publishers_grammar():
    assert classification_table_file_name(119, 2) == "tbl119pl_2nd.htm"
    assert classification_table_file_name(119, 1, "code") == "tbl119cd_1st.htm"
    assert classification_table_locator(119, 2) == "https://uscode.house.gov/classification/tbl119pl_2nd.htm"
    with pytest.raises(UsCodeSourceError, match="session must be 1 or 2"):
        classification_table_file_name(119, 3)
    with pytest.raises(UsCodeSourceError, match="order must be"):
        classification_table_file_name(119, 2, "popular")  # type: ignore[arg-type]


def test_the_table_proves_the_congress_and_session_its_caption_states():
    table = parse_classification_table(TABLE, congress=119, session=2)
    assert table.source == "classification-table"
    assert (table.congress, table.session, table.order) == (119, 2, "public-law")
    assert table.identity_basis == ("congress:native", "session:native")
    assert table.heading == "TABLE OF CLASSIFICATIONS FOR PUBLIC LAWS"
    assert table.stated_laws == "Public Law 119-70 and Public Laws 119-74 through 119-110"
    assert len(table.stated_law_numbers) == 38
    assert table.stated_law_numbers[0] == "119-70" and table.stated_law_numbers[-1] == "119-110"
    assert table.statutes_at_large_volume == "140"
    assert table.prepared_date == "September 16, 2026"


def test_a_table_for_another_session_is_refused_by_name():
    with pytest.raises(UsCodeSourceError, match="another Congress or session"):
        parse_classification_table(TABLE, congress=119, session=1)


def test_a_table_whose_caption_states_another_congress_is_refused():
    relabelled = TABLE.replace(b"119th Congress, 2nd Session", b"118th Congress, 2nd Session", 1)
    with pytest.raises(UsCodeSourceError, match="another Congress or session"):
        parse_classification_table(relabelled, congress=119, session=2)


def test_a_page_without_its_column_header_or_pre_block_is_refused():
    headerless = TABLE.replace(b"Title", b"Titlz", 1)
    with pytest.raises(UsCodeSourceError, match="lacks its column header"):
        parse_classification_table(headerless, congress=119, session=2)
    preless = TABLE[: TABLE.index(b"<PRE>")] + b"</body></html>"
    with pytest.raises(UsCodeSourceError, match="exactly one <PRE> block"):
        parse_classification_table(preless, congress=119, session=2)


def test_an_empty_or_truncated_table_is_refused_not_read_as_a_session_that_classified_nothing():
    empty = cut_pre_block(TABLE)
    with pytest.raises(UsCodeSourceError, match="states no rows"):
        parse_classification_table(empty, congress=119, session=2)
    with pytest.raises(UsCodeSourceError, match="not closed by </html>"):
        parse_classification_table(TABLE[:4096], congress=119, session=2)


def test_more_rows_than_max_rows_is_a_refusal():
    with pytest.raises(UsCodeSourceError, match="more rows than max_rows"):
        parse_classification_table(TABLE, congress=119, session=2, max_rows=5)


def test_rows_sliced_at_the_headers_offsets_and_their_law_numbers_held_to_the_caption_congress():
    table = parse_classification_table(TABLE, congress=119, session=2)
    first = table.records[0]
    assert (first.seq, first.usc_title, first.usc_section, first.description) == (0, "42", "5301", "nt new")
    assert (first.law_number, first.act_section) == ("119-70", "1")
    assert first.statutes_at_large_page == "3"
    assert (first.link_volume, first.link_page) == ("140", "3")
    # A page span keeps the printed column whole and states no statviewer link.
    spanned = next(record for record in table.records if record.link_volume is None)
    assert (spanned.usc_title, spanned.usc_section) == ("42", "1396a")
    assert spanned.description is None
    assert spanned.act_section == "6101(a)-(b)(2)"
    assert spanned.statutes_at_large_page == "637, 638"


def _first_data_line(body: bytes) -> bytes:
    start = body.index(b"<PRE>") + len(b"<PRE>")
    lines = body[start : body.index(b"</pre>")].split(b"\n")
    header = next(i for i, line in enumerate(lines) if b"Title" in line and b"Stat." in line)
    return lines[header + 2]


def test_a_row_named_for_another_congress_is_refused():
    stray = cut_pre_block(TABLE, _first_data_line(TABLE).replace(b"119-70", b"118-70"))
    with pytest.raises(UsCodeSourceError, match="names a law of another Congress"):
        parse_classification_table(stray, congress=119, session=2)
    numberless = cut_pre_block(TABLE, _first_data_line(TABLE).replace(b"119-70", b"      "))
    with pytest.raises(UsCodeSourceError, match="states no public law number"):
        parse_classification_table(numberless, congress=119, session=2)


def test_the_index_and_table_arrive_through_the_acquirer_with_evidence():
    class Transport(httpx.MockTransport):
        def __init__(self, *responses):
            self.responses = iter(responses)
            self.calls = []
            super().__init__(self.handle)

        def handle(self, request):
            self.calls.append(request)
            return next(self.responses)

    transport = Transport(
        httpx.Response(200, stream=httpx.ByteStream(INDEX), headers={"content-type": "text/html;charset=UTF-8"}),
        httpx.Response(200, stream=httpx.ByteStream(TABLE), headers={"content-type": "text/html;charset=UTF-8"}),
    )
    with UsCodeAcquirer(budget=BUDGET, transport=transport) as source:
        index = source.acquire_classification_index()
        table = source.acquire_classification_table(119, 2)
    assert index.result.title == INDEX_TITLE and index.capture.byte_size == len(INDEX)
    assert index.capture.requested_url == CLASSIFICATION_INDEX_URL
    assert index.operation == "classification-index" and index.selection is None
    assert (table.result.congress, table.result.session) == (119, 2)
    assert table.operation == "classification-table"
    assert table.selection == {"congress": 119, "session": 2, "order": "public-law"}
    assert table.capture.requested_url == classification_table_locator(119, 2)
    assert index.request_count == 1 and table.request_count == 1  # per capture call
