"""FERC eLibrary routes answer envelope JSON, page by body-advanced curPage, and record their empties.

The keyless WebAPI serves ``{"DataList": [...], "ErrorList": []}`` on keyed GET
routes and ``{"searchHits": [...], "totalHits", "numHits", "success"}`` on
``Search/AdvancedSearch``; its paging state lives in the request body, so this
module's walk advances ``curPage`` itself and holds the shared traversal's
refusals. Live fixtures cover populated and requested-empty answers; the latter
remains an observation, never absence.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.paged_json import (
    DeclaredCountChanged,
    DeclaredCountMismatch,
    PagedJsonBudget,
    PagedJsonSourceError,
)
from spicy_docs.sources.ferc.elibrary import (
    ACCESSION_FIELD,
    ADVANCED_SEARCH_URL,
    API,
    DOCKET_SHEET_URL,
    FERC_ELIBRARY,
    RULEMAKING_COMMENT,
    FercElibraryAccessRefusedError,
    FercElibraryError,
    FercElibraryReader,
    accession_number,
    docket_description_url,
    docket_id,
    docket_search_body,
    docket_sheet_body,
    docket_sheet_document_accession,
    docket_sheet_rows,
    file_list_url,
    new_docket_identity,
    new_dockets_url,
    search_hit_reference,
    sub_dockets_url,
)
from spicy_docs.sources.ferc.readers import (
    REQUESTED_EMPTY,
    FercDocketSheetReader,
    FercElibraryAccessionReader,
    FercElibraryCommentReader,
    FercNewDocketReader,
)
from spicy_docs.transport import retry
from spicy_docs.transport.captured import attached_capture
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "ferc"
DESCRIPTION = (FIXTURES / "docket-description-rm24-5.json").read_bytes()
EMPTY_SEARCH = (FIXTURES / "advanced-search-empty-rm24-5.json").read_bytes()
ATMS_EMPTY = (FIXTURES / "docket-atmsdocs-empty.json").read_bytes()
SEARCH_P1 = (FIXTURES / "advanced-search-rm24-5-comments-p1.json").read_bytes()
SEARCH_P2 = (FIXTURES / "advanced-search-rm24-5-comments-p2.json").read_bytes()
FILE_LIST = (FIXTURES / "file-list-p8-20251125-3057.json").read_bytes()
SUB_DOCKETS = (FIXTURES / "sub-dockets-rm24-5.json").read_bytes()
NEW_DOCKETS_CREATE = (FIXTURES / "new-dockets-rbcreatedate-2026-09-23-2026-09-25.json").read_bytes()
NEW_DOCKETS_FILING = (FIXTURES / "new-dockets-rbfilingdate-2026-09-20-2026-09-25.json").read_bytes()
DOCKET_SHEET_LIVE = (FIXTURES / "docket-sheet-er11-4046-001.json").read_bytes()
DOCKET_SHEET_P1 = (FIXTURES / "docket-sheet-er11-4046-001-p1.json").read_bytes()
DOCKET_SHEET_P2 = (FIXTURES / "docket-sheet-er11-4046-001-p2.json").read_bytes()
DOCKET_SHEET_EMPTY = json.dumps(
    {"DataList": [], "ErrorList": [], "Page": {"totalHits": 0, "numHits": 100, "pageNumber": 0}}
).encode()
CLASS_TYPES = json.loads((FIXTURES / "class-types-trimmed.json").read_text())
BUDGET = PagedJsonBudget(4, 256 * 1024, 7, 0)
ACCESSION = "20251125-3057"
ERROR_LIST_BODY = json.dumps({"DataList": [], "ErrorList": ["request denied"]}).encode()


def json_response(body, status=200, *, content_type="application/json"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

    def __init__(self, *bodies):
        self.bodies = iter(bodies)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        body = next(self.bodies, None)
        if body is None:
            return json_response(ERROR_LIST_BODY)
        status = 401 if body == b"__401__" else 200
        return json_response(body, status)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_family_and_identity_grammars():
    """The family is keyless on the elibrary host; dockets and accessions carry their own grammar."""
    assert FERC_ELIBRARY.requires_credential is False and FERC_ELIBRARY.host == "elibrary.ferc.gov"
    assert docket_id("rm24-5") == "RM24-5" and docket_id(" AD24-2-000 ") == "AD24-2-000"
    # The one-letter P (hydropower) is a published prefix; a three-letter one is not.
    assert docket_id("p-1234-000") == "P-1234-000" and docket_id("P-14683") == "P-14683"
    # Interlocking-directorate dockets spell a serial number too (live new-docket answer, 2026-09-25).
    assert docket_id("ID-10800-000") == "ID-10800-000" and docket_id("id-10800") == "ID-10800"
    assert accession_number("20240418-4000") == "20240418-4000" and accession_number(" 19990101-301 ") == "19990101-301"
    for bad_docket in ("RM-5", "rm24-5-00000", "24-5", "RM24-5-0", "QQQ1-2", "X1-2", "QQ-10800", "E-1234", ""):
        with pytest.raises(FercElibraryError):
            docket_id(bad_docket)
    for bad_accession in ("2024-4000", "20240418-40", "20240418-400000", "2024041 8-4000"):
        with pytest.raises(FercElibraryError):
            accession_number(bad_accession)


def test_route_urls_and_search_body():
    """Routes live under the discovered API base and the search body is spelled as the SPA sends it."""
    assert docket_description_url("RM24-5") == f"{API}/Docket/getDocketDescription/RM24-5"
    assert sub_dockets_url("RM24-5") == f"{API}/Docket/getSubDocketSearch/RM24-5"
    assert file_list_url(ACCESSION) == f"{API}/File/GetFileListFromP8/{ACCESSION}"
    assert ADVANCED_SEARCH_URL == f"{API}/Search/AdvancedSearch"
    today = datetime.now(UTC).date().isoformat()
    body = docket_search_body("RM24-5", document_class=(RULEMAKING_COMMENT,), results_per_page=2)
    assert body["docketSearches"] == [{"docketNumber": "RM24-5", "subDocketNumbers": []}]
    assert body["classTypes"] == [{"documentClass": "Comments/Protest", "documentType": "Rulemaking Comment"}]
    assert body["dateSearches"] == [{"dateType": "filed_date", "startDate": "1904-01-01", "endDate": today}]
    assert body["allDates"] is True and body["availability"] is None and body["groupBy"] == "NONE"
    assert body["searchText"] == "*" and body["searchFullText"] is True and body["searchDescription"] is True
    assert body["accessionNumber"] is None and body["eFiling"] is False and body["idolResultID"] is None
    assert body["affiliations"] == [] and body["categories"] == [] and body["libraries"] == []
    assert body["curPage"] == 1 and body["resultsPerPage"] == 2 and body["sortBy"] == ""
    assert set(body) == {
        "searchText",
        "searchFullText",
        "searchDescription",
        "dateSearches",
        "categories",
        "libraries",
        "classTypes",
        "affiliations",
        "docketSearches",
        "accessionNumber",
        "eFiling",
        "availability",
        "resultsPerPage",
        "curPage",
        "sortBy",
        "groupBy",
        "idolResultID",
        "allDates",
    }
    for kwargs in ({"results_per_page": 0}, {"results_per_page": 101}, {"cur_page": 0}):
        with pytest.raises(FercElibraryError):
            docket_search_body("RM24-5", **kwargs)
    with pytest.raises(FercElibraryError):
        docket_search_body("RM24-5", document_class=(["Comments/Protest", "Rulemaking Comment"],))


def test_search_body_date_window_and_token_parameters():
    """A caller-supplied window narrows dateSearches and flips allDates; malformed inputs refuse."""
    today = datetime.now(UTC).date().isoformat()
    narrowed = docket_search_body("RM24-5", date_from="2024-01-15", date_to="2024-12-31")
    assert narrowed["dateSearches"] == [{"dateType": "filed_date", "startDate": "2024-01-15", "endDate": "2024-12-31"}]
    assert narrowed["allDates"] is False
    from_only = docket_search_body("RM24-5", date_from="2024-01-15")
    assert from_only["dateSearches"] == [{"dateType": "filed_date", "startDate": "2024-01-15", "endDate": today}]
    assert from_only["allDates"] is False
    to_only = docket_search_body("RM24-5", date_to="2024-01-15")
    assert to_only["dateSearches"] == [{"dateType": "filed_date", "startDate": "1904-01-01", "endDate": "2024-01-15"}]
    assert to_only["allDates"] is False
    carried = docket_search_body("RM24-5", idol_result_id="SQ1-2-3")
    assert carried["idolResultID"] == "SQ1-2-3"
    for kwargs in (
        {"date_from": "2024-1-1"},
        {"date_from": "01-15-2024"},
        {"date_to": "2024-13-01"},
        {"date_from": "2025-01-01", "date_to": "2024-01-01"},
        {"idol_result_id": 42},
    ):
        with pytest.raises(FercElibraryError):
            docket_search_body("RM24-5", **kwargs)


def test_class_types_fixture_pins_the_comment_vocabulary():
    """The publisher's own class vocabulary names rulemaking comments; the module quotes it."""
    assert RULEMAKING_COMMENT == ("Comments/Protest", "Rulemaking Comment")
    row = next(item for item in CLASS_TYPES if item["Type"] == "Rulemaking Comment")
    assert row["Library"] == "RM/O/Gen/H/G/E" and row["Category"] == "Submittal"


def test_search_builder_matches_successful_browser_wire_fields():
    """The builder emits the browser's own wire body, first page per the paginator convention."""
    browser = json.loads((FIXTURES / "advanced-search-browser-request.json").read_text())
    # Both 0 and 1 select the first page live; the builder follows the bundle's
    # paginator (curPage: pageIndex+1) and keeps idolResultID null until the
    # publisher returns a token. The browser's request pinned the day's date;
    # the builder recomputes today (UTC) with the same start.
    browser.update(
        curPage=1,
        idolResultID=None,
        dateSearches=[
            {
                "dateType": "filed_date",
                "startDate": "1904-01-01",
                "endDate": datetime.now(UTC).date().isoformat(),
            }
        ],
    )
    assert docket_search_body("RM24-5") == browser


def test_reader_sends_the_spa_headers_on_every_request():
    """Every request carries the application id, one stable session id and a fresh correlation id."""
    transport = Transport(DESCRIPTION, DESCRIPTION)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        source.docket_description("RM24-5")
        source.docket_description("RM24-5")
    first, second = transport.calls
    assert first.headers["x-applicationid"] == "52f6cc3e-3b73-4b1d-9668-05c32c17bf38"
    assert first.headers["x-sessionid"] == second.headers["x-sessionid"]
    assert first.headers["x-correlationid"] != second.headers["x-correlationid"]
    assert first.headers["user-agent"].startswith("Mozilla/5.0")
    assert str(first.url) == docket_description_url("RM24-5")


def test_docket_description_and_sub_dockets_parse_the_envelope():
    transport = Transport(DESCRIPTION, SUB_DOCKETS, ERROR_LIST_BODY)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        description = source.docket_description("rm24-5")
        assert (description.description, description.kind) == ("Notice of Proposed Rulemaking", "DKT")
        assert source.sub_dockets("RM24-5") == ("000",)
        with pytest.raises(FercElibraryError, match="ErrorList"):
            source.sub_dockets("RM24-5")
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(ATMS_EMPTY)) as source,
        pytest.raises(FercElibraryError, match="answered an empty DataList"),
    ):
        source.docket_description("RM24-5")


def test_file_list_reads_datalist_rows_and_refuses_error_lists():
    """The live 2026-09-24 capture: one row keyed by a GUID, with the publisher's own field spellings."""
    transport = Transport(FILE_LIST)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        files = source.file_list(ACCESSION)
    assert [row["ID"] for row in files.records] == ["C608268A-B6D1-CF34-93C1-9ABC04900000"]
    assert files.records[0]["Orig_File_Name"] == "ER25-3543-000.docx"
    assert files.records[0]["File_Type_Code"] == "DOCX" and files.records[0]["Availability_Mode"] == "P"
    assert files.accession == ACCESSION
    assert str(transport.calls[0].url) == file_list_url(ACCESSION)
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(ERROR_LIST_BODY)) as source,
        pytest.raises(FercElibraryError, match="ErrorList"),
    ):
        source.file_list(ACCESSION)


def search_body(page_size=2):
    return docket_search_body("RM24-5", document_class=(RULEMAKING_COMMENT,), results_per_page=page_size)


def edited(**changes) -> bytes:
    page = json.loads(SEARCH_P1)
    page.update(changes)
    return json.dumps(page).encode()


def test_search_walk_advances_curpage_and_carries_the_idol_token():
    """The walk pages by request body: curPage +1 per full page, the previous searchResultId carried forward."""
    transport = Transport(SEARCH_P1, SEARCH_P2)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.search_pages(search_body()))
    assert [len(page.records) for page in pages] == [2, 1]
    assert [page.declared_count for page in pages] == [3, 3]
    assert pages[1].next_body is None
    sent = [json.loads(call.read()) for call in transport.calls]
    assert [body["curPage"] for body in sent] == [1, 2]
    assert sent[1]["idolResultID"] == "SQ1-2-3"
    assert all(body["docketSearches"][0]["docketNumber"] == "RM24-5" for body in sent)
    assert transport.calls[0].headers["content-type"] == "application/json"


def test_live_comment_pages_replay_with_source_count_and_identity():
    bodies = [(FIXTURES / f"advanced-search-rm24-5-live-comments-p{page}.json").read_bytes() for page in (1, 2, 3)]
    transport = Transport(*bodies)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.search_pages(search_body()))
    rows = [row for page in pages for row in page.records]
    assert [len(page.records) for page in pages] == [2, 2, 1]
    assert {page.declared_count for page in pages} == {5}
    assert len({search_hit_reference(row) for row in rows}) == 5
    assert [row[ACCESSION_FIELD] for row in rows] == [
        "20240807-5052",
        "20240807-5051",
        "20240710-5055",
        "20240708-5145",
        "20240702-5018",
    ]
    assert all(
        {"documentClass": RULEMAKING_COMMENT[0], "documentType": RULEMAKING_COMMENT[1]} in row["classTypes"]
        for row in rows
    )
    sent = [json.loads(call.read()) for call in transport.calls]
    assert [body["curPage"] for body in sent] == [1, 2, 3]
    # The live publisher returned no searchResultId, so idolResultID stays null
    # across pages, exactly as the SPA's paginator leaves it.
    assert [body["idolResultID"] for body in sent] == [None, None, None]
    assert all(
        body["classTypes"] == [{"documentClass": RULEMAKING_COMMENT[0], "documentType": RULEMAKING_COMMENT[1]}]
        for body in sent
    )


def test_full_last_page_uses_source_terminal_empty_with_unchanged_total():
    pages = [
        json.loads((FIXTURES / f"advanced-search-rm24-5-live-comments-p{page}.json").read_text()) for page in (1, 2, 3)
    ]
    combined = {**pages[0], "searchHits": [row for page in pages for row in page["searchHits"]], "numHits": 5}
    terminal = (FIXTURES / "advanced-search-rm24-5-live-terminal.json").read_bytes()
    with FercElibraryReader(budget=BUDGET, transport=Transport(json.dumps(combined).encode(), terminal)) as source:
        observed = list(source.search_pages(search_body(page_size=5)))
    assert [len(page.records) for page in observed] == [5, 0]
    assert {page.declared_count for page in observed} == {5}


def test_search_walk_refusals():
    """A silent or inconsistent end refuses: page bound, count mismatch, a moved count, and the envelope's own statements."""
    two_more_full = {**json.loads(SEARCH_P1), "totalHits": 4}
    distinct_second = {
        **two_more_full,
        "searchHits": [
            {**row, "reference": f"20240419-400{index}"} for index, row in enumerate(two_more_full["searchHits"])
        ],
    }
    with (
        FercElibraryReader(
            budget=BUDGET, transport=Transport(json.dumps(two_more_full).encode(), json.dumps(distinct_second).encode())
        ) as source,
        pytest.raises(FercElibraryError, match="page bound reached"),
    ):
        list(source.search_pages(search_body(), max_pages=2))
    declared_short = {**json.loads(SEARCH_P2), "totalHits": 4}
    with FercElibraryReader(
        budget=BUDGET, transport=Transport(json.dumps(two_more_full).encode(), json.dumps(declared_short).encode())
    ) as source:
        with pytest.raises(DeclaredCountMismatch) as mismatch:
            list(source.search_pages(search_body()))
        assert (mismatch.value.declared, mismatch.value.observed) == (4, 3)
    with FercElibraryReader(budget=BUDGET, transport=Transport(SEARCH_P1, edited(totalHits=4))) as source:
        with pytest.raises(DeclaredCountChanged) as changed:
            list(source.search_pages(search_body()))
        assert (changed.value.declared, changed.value.changed_to) == (3, 4)
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(SEARCH_P1, SEARCH_P1)) as source,
        pytest.raises(FercElibraryError, match="more records than it declared"),
    ):
        list(source.search_pages(search_body()))
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(edited(numHits=1))) as source,
        pytest.raises(FercElibraryError, match="numHits differs"),
    ):
        list(source.search_pages(search_body()))
    with (
        FercElibraryReader(
            budget=BUDGET, transport=Transport(edited(success=False, errorMessage="query refused"))
        ) as source,
        pytest.raises(FercElibraryError, match="success:false.*query refused"),
    ):
        list(source.search_pages(search_body()))


def test_an_empty_search_walk_is_an_observation_not_absence():
    """The live RM24-5 answer (success, zero rows, zero declared) is a complete walk that serves nothing."""
    transport = Transport(EMPTY_SEARCH)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.search_pages(search_body()))
    assert pages and pages[0].records == () and pages[0].declared_count == 0
    assert len(transport.calls) == 1


def test_access_refusal_aborts_and_only_404_is_route_absence():
    """A 401 is recast as this family's refusal but keeps the abort semantics; 404 names its route."""
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(b"__401__")) as source,
        pytest.raises(FercElibraryAccessRefusedError) as refused,
    ):
        source.docket_description("RM24-5")
    assert isinstance(refused.value, CredentialRefusedError)
    missing = httpx.MockTransport(
        lambda request: httpx.Response(
            404, stream=httpx.ByteStream(b"{}"), headers={"content-type": "application/json"}
        )
    )
    with (
        FercElibraryReader(budget=BUDGET, transport=missing) as source,
        pytest.raises(PagedJsonSourceError, match="HTTP 404"),
    ):
        source.docket_description("RM24-5")


def test_comment_reader_semantics():
    """Rows yield as served; a requested-empty docket and a refused one both stay retryable, each with its reason."""
    transport = Transport(SEARCH_P1, SEARCH_P2, EMPTY_SEARCH, ERROR_LIST_BODY)
    reader = FercElibraryCommentReader(
        FercElibraryReader(budget=BUDGET, transport=transport),
        ["rm24-5", "AD24-2", "AD24-3"],
        results_per_page=2,
    )
    records = list(reader.iter_records())
    assert [row[ACCESSION_FIELD] for row in records] == ["20240418-4000", "20240418-4001", "20240419-4000"]
    assert records[0] == json.loads(SEARCH_P1)["searchHits"][0]
    assert reader.last_keys == ["RM24-5"]
    assert reader.failed_keys == ["AD24-2", "AD24-3"]
    assert reader.failure_reasons["AD24-2"] == REQUESTED_EMPTY
    assert set(reader.empty_observations) == {"AD24-2"}
    assert datetime.fromisoformat(reader.empty_observations["AD24-2"]).tzinfo is not None
    assert "success:false" in reader.failure_reasons["AD24-3"]
    with pytest.raises(CredentialRefusedError):
        list(
            FercElibraryCommentReader(
                FercElibraryReader(budget=BUDGET, transport=Transport(b"__401__")), ["RM24-5"]
            ).iter_records()
        )


def test_a_refused_input_identity_lands_in_failed_keys_and_the_run_continues():
    """A malformed docket or accession is a failed key with its reason, not an exception after partial yields."""
    comments = FercElibraryCommentReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(SEARCH_P1, SEARCH_P2)),
        ["not-a-docket", "RM24-5"],
        results_per_page=2,
    )
    assert len(list(comments.iter_records())) == 3
    assert comments.failed_keys == ["not-a-docket"] and comments.last_keys == ["RM24-5"]
    assert "docket must be" in comments.failure_reasons["not-a-docket"]
    accessions = FercElibraryAccessionReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(FILE_LIST)), ["2024-4000", ACCESSION]
    )
    assert len(list(accessions.iter_records())) == 1
    assert accessions.failed_keys == ["2024-4000"] and accessions.last_keys == [ACCESSION]
    assert "accession must be" in accessions.failure_reasons["2024-4000"]


def test_every_new_docket_identity_feeds_the_comment_and_sheet_readers():
    """The live window's identities, the serial-numbered ``ID-10800-000`` included, pass the docket grammar."""
    identities = [row["DocketFullNumber"] for row in json.loads(NEW_DOCKETS_FILING)["DataList"]]
    assert "ID-10800-000" in identities
    for identity in identities:
        assert docket_id(identity) == identity
        docket, _, subdocket = identity.rpartition("-")
        assert FercDocketSheetReader(FercElibraryReader(budget=BUDGET), docket, subdocket).key == identity


def test_comment_reader_refuses_rows_without_identity():
    """A row without the publisher's reference field fails its docket rather than reading as a record."""
    identityless = edited(searchHits=[{ACCESSION_FIELD: "20240418-4000"}], numHits=1, totalHits=1)
    reader = FercElibraryCommentReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(identityless)), ["RM24-5"], results_per_page=2
    )
    assert list(reader.iter_records()) == []
    assert reader.last_keys == [] and reader.failed_keys == ["RM24-5"]
    assert "reference" in reader.failure_reasons["RM24-5"]
    good = json.loads(SEARCH_P1)["searchHits"][0]
    assert search_hit_reference(good) == "20240418-4000"


@pytest.mark.parametrize("within_page", [False, True])
def test_repeated_references_cannot_complete_a_docket(within_page):
    first = json.loads(SEARCH_P1)["searchHits"][0]
    duplicate = edited(
        searchHits=[first, first] if within_page else [first],
        numHits=2 if within_page else 1,
        totalHits=2 if within_page else 3,
    )
    bodies = (duplicate,) if within_page else (SEARCH_P1, duplicate)
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(*bodies)) as source,
        pytest.raises(FercElibraryError, match="repeated reference") as raised,
    ):
        list(source.search_pages(search_body()))
    assert attached_capture(raised.value).body == duplicate
    reader = FercElibraryCommentReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(*bodies)), ["RM24-5"], results_per_page=2
    )
    assert list(reader.iter_records()) == []
    assert reader.last_keys == [] and reader.failed_keys == ["RM24-5"]
    assert "repeated reference" in reader.failure_reasons["RM24-5"]


def test_accession_reader_semantics():
    """Accessions with rows are consumed; a requested-empty list stays unresolved with its timestamp."""
    transport = Transport(FILE_LIST, ATMS_EMPTY, ERROR_LIST_BODY)
    reader = FercElibraryAccessionReader(
        FercElibraryReader(budget=BUDGET, transport=transport), [ACCESSION, "20240419-4000", "20240420-4000"]
    )
    records = list(reader.iter_records())
    assert len(records) == 1 and records[0]["Accession_Number"] == ACCESSION
    assert reader.last_keys == [ACCESSION]
    assert reader.failed_keys == ["20240419-4000", "20240420-4000"]
    assert reader.failure_reasons["20240419-4000"] == REQUESTED_EMPTY
    assert set(reader.empty_observations) == {"20240419-4000"}
    assert "ErrorList" in reader.failure_reasons["20240420-4000"]
    with pytest.raises(CredentialRefusedError):
        list(
            FercElibraryAccessionReader(
                FercElibraryReader(budget=BUDGET, transport=Transport(b"__401__")), [ACCESSION]
            ).iter_records()
        )


def test_new_dockets_url_spelling_date_transform_and_validation():
    """The window spells MM-dd-yyyy from YYYY-MM-DD inputs; unknown modes, reversed windows and odd sorts refuse."""
    assert (
        new_dockets_url("rbCreateDate", "2026-09-23", "2026-09-25")
        == f"{API}/Docket/GetATMSdocs/rbCreateDate/09-23-2026/09-25-2026/DocketFullNumber"
    )
    assert (
        new_dockets_url("rbFilingDate", "2026-09-20", "2026-09-25", sort="DocketFullNumber")
        == f"{API}/Docket/GetATMSdocs/rbFilingDate/09-20-2026/09-25-2026/DocketFullNumber"
    )
    for bad in (
        ("rbFoo", "2026-09-23", "2026-09-25"),
        ("rbCreateDate", "2026-9-23", "2026-09-25"),
        ("rbCreateDate", "2026-13-23", "2026-09-25"),
        ("rbCreateDate", "2026-09-25", "2026-09-23"),
        ("rbCreateDate", "2026-09-23", "2026-09-25", ""),
        ("rbCreateDate", "2026-09-23", "2026-09-25", "../File/DownloadPDF"),
        ("rbCreateDate", "2026-09-23", "2026-09-25", "Docket?api_key=x"),
        ("rbCreateDate", "2026-09-23", "2026-09-25", 42),
    ):
        with pytest.raises(FercElibraryError):
            new_dockets_url(*bad)


def test_new_docket_identity_is_the_served_docket_full_number_and_is_required():
    row = json.loads(NEW_DOCKETS_CREATE)["DataList"][3]
    assert new_docket_identity(row) == "ER10-1874-021"
    for bad in (
        {},
        {"DocketFullNumber": ""},
        {"DocketFullNumber": "  "},
        {"DocketFullNumber": 42},
        {"DocketFullNumber": None},
    ):
        with pytest.raises(FercElibraryError, match="DocketFullNumber"):
            new_docket_identity(bad)


def test_new_dockets_reader_walks_one_window_in_one_get():
    """One window, one GET: every row verbatim plus its identity and the capture digest."""
    transport = Transport(NEW_DOCKETS_CREATE)
    reader = FercNewDocketReader(
        FercElibraryReader(budget=BUDGET, transport=transport), "rbCreateDate", "2026-09-23", "2026-09-25"
    )
    records = list(reader.iter_records())
    served = json.loads(NEW_DOCKETS_CREATE)["DataList"]
    digest = "sha256:" + hashlib.sha256(NEW_DOCKETS_CREATE).hexdigest()
    assert records == [{**row, "identity": row["DocketFullNumber"], "captureSha256": digest} for row in served]
    assert reader.last_keys == ["CP26-585-000", "EG26-326-000", "EG26-327-000", "ER10-1874-021"]
    assert reader.failed_keys == [] and reader.empty_observations == {}
    assert len(transport.calls) == 1
    assert str(transport.calls[0].url) == new_dockets_url("rbCreateDate", "2026-09-23", "2026-09-25")


def test_a_window_with_an_identityless_row_yields_nothing_and_fails_its_window():
    """Every row's identity is checked before any yield, so a bad row cannot leave a half-consumed window."""
    value = json.loads(NEW_DOCKETS_CREATE)
    value["DataList"][2]["DocketFullNumber"] = ""
    reader = FercNewDocketReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(json.dumps(value).encode())),
        "rbCreateDate",
        "2026-09-23",
        "2026-09-25",
    )
    assert list(reader.iter_records()) == []
    assert reader.last_keys == [] and reader.failed_keys == [reader.window]
    assert "DocketFullNumber" in reader.failure_reasons[reader.window]


def test_new_dockets_route_parses_the_envelope_and_refuses_error_lists():
    """Both live 2026-09-25 fixture windows parse; a non-empty ErrorList refuses."""
    transport = Transport(NEW_DOCKETS_FILING, ERROR_LIST_BODY)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        listing = source.new_dockets("rbFilingDate", "2026-09-20", "2026-09-25")
        assert [row["DocketFullNumber"] for row in listing.records] == [
            "AC26-103-000",
            "CD26-5-000",
            "CP26-584-000",
            "ER10-1874-021",
            "ID-10800-000",
        ]
        assert listing.capture.body == NEW_DOCKETS_FILING
        with pytest.raises(FercElibraryError, match="ErrorList"):
            source.new_dockets("rbFilingDate", "2026-09-20", "2026-09-25")


def test_new_dockets_empty_answer_is_an_observation_with_retry_posture():
    """A zero window is a publisher-side bug: a failed key with its timestamp, re-asked until rows arrive."""
    elibrary = FercElibraryReader(budget=BUDGET, transport=Transport(ATMS_EMPTY, NEW_DOCKETS_CREATE))
    reader = FercNewDocketReader(elibrary, "rbCreateDate", "2026-09-23", "2026-09-25")
    assert list(reader.iter_records()) == []
    assert reader.last_keys == [] and reader.failed_keys == [reader.window]
    assert reader.failure_reasons == {reader.window: REQUESTED_EMPTY}
    assert datetime.fromisoformat(reader.empty_observations[reader.window]).tzinfo is not None
    rows = list(reader.iter_records())
    assert len(rows) == 4 and reader.failed_keys == [] and reader.empty_observations == {}
    assert reader.last_keys[-1] == "ER10-1874-021"


def test_new_dockets_reader_defaults_to_the_publishers_ten_day_cap_and_allows_override():
    """The default window is the form's own cap (today minus ten days to today); a wider override is the caller's."""
    today = datetime.now(UTC).date()
    default_from = (today - timedelta(days=10)).isoformat()
    transport = Transport(NEW_DOCKETS_CREATE)
    reader = FercNewDocketReader(FercElibraryReader(budget=BUDGET, transport=transport), "rbCreateDate")
    assert reader.window == f"rbCreateDate {default_from}..{today.isoformat()}"
    list(reader.iter_records())
    assert str(transport.calls[0].url) == new_dockets_url("rbCreateDate", default_from, today.isoformat())
    over = FercNewDocketReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(NEW_DOCKETS_CREATE)),
        "rbCreateDate",
        "2026-09-14",
        "2026-09-25",
    )
    assert over.window == "rbCreateDate 2026-09-14..2026-09-25"
    with pytest.raises(FercElibraryError):
        FercNewDocketReader(FercElibraryReader(budget=BUDGET, transport=Transport(NEW_DOCKETS_CREATE)), "rbFoo")


def test_new_dockets_reader_records_a_refused_window_and_aborts_on_401():
    """An ErrorList refusal keeps the window in failed_keys with its scrubbed reason; a 401 still aborts."""
    reader = FercNewDocketReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(ERROR_LIST_BODY)),
        "rbFilingDate",
        "2026-09-20",
        "2026-09-25",
    )
    assert list(reader.iter_records()) == []
    assert reader.failed_keys == ["rbFilingDate 2026-09-20..2026-09-25"]
    assert "ErrorList" in reader.failure_reasons["rbFilingDate 2026-09-20..2026-09-25"]
    with pytest.raises(CredentialRefusedError):
        list(
            FercNewDocketReader(
                FercElibraryReader(budget=BUDGET, transport=Transport(b"__401__")),
                "rbCreateDate",
                "2026-09-23",
                "2026-09-25",
            ).iter_records()
        )


def sheet_body(page_size=100):
    return docket_sheet_body("ER11-4046", "001", num_hits=page_size)


def sheet_edited(**changes) -> bytes:
    value = json.loads(DOCKET_SHEET_P1)
    value.update(changes)
    return json.dumps(value).encode()


def sheet_page(page: dict, **page_changes) -> bytes:
    value = dict(page)
    value["Page"] = {**page["Page"], **page_changes}
    return json.dumps(value).encode()


def test_docket_sheet_body_spells_the_measured_wire_shape_and_validates():
    """The body is the SPA's own spelling: lowercase dockets, MM-dd-yyyy dates, zero-based pageNumber."""
    today = datetime.now(UTC).date()
    body = docket_sheet_body("ER11-4046", "001")
    assert body == {
        "dockets": "er11-4046",
        "subdockets": "001",
        "filed_date_beg": "01-01-1960",
        "filed_date_end": today.strftime("%m-%d-%Y"),
        "complete_flag": 0,
        "numHits": 100,
        "pageNumber": 0,
    }
    assert set(body) == {
        "dockets",
        "subdockets",
        "filed_date_beg",
        "filed_date_end",
        "complete_flag",
        "numHits",
        "pageNumber",
    }
    narrowed = docket_sheet_body(
        "rm24-5", date_from="2024-01-15", date_to="2024-12-31", complete_flag=1, num_hits=10, page_number=3
    )
    assert narrowed["dockets"] == "rm24-5" and narrowed["filed_date_beg"] == "01-15-2024"
    assert narrowed["filed_date_end"] == "12-31-2024" and narrowed["complete_flag"] == 1
    assert narrowed["numHits"] == 10 and narrowed["pageNumber"] == 3
    for bad_docket in ("24-5", "QQQ1-2", ""):
        with pytest.raises(FercElibraryError):
            docket_sheet_body(bad_docket)
    for kwargs in (
        {"subdockets": 42},
        {"date_from": "2024-1-15"},
        {"date_to": "01-01-2024"},
        {"date_from": "2025-01-01", "date_to": "2024-01-01"},
        {"complete_flag": 2},
        {"complete_flag": True},
        {"num_hits": 0},
        {"num_hits": 101},
        {"num_hits": True},
        {"page_number": -1},
        {"page_number": True},
    ):
        with pytest.raises(FercElibraryError):
            docket_sheet_body("ER11-4046", **kwargs)


def test_docket_sheet_rows_flatten_verbatim_and_require_the_accession_identity():
    """Each DocumentsItem entry is one document; AuthorsItem/FedCitesItem ride verbatim beside every one."""
    live = json.loads(DOCKET_SHEET_LIVE)
    documents = [document for row in live["DataList"] for document in docket_sheet_rows(row)]
    assert documents == [{**row["DocumentsItem"][0], "AuthorsItem": [], "FedCitesItem": []} for row in live["DataList"]]
    assert [docket_sheet_document_accession(document) for document in documents] == [
        "20110714-5024",
        "20110715-3051",
        "20110816-3002",
    ]
    multi = {
        "DocumentsItem": [live["DataList"][0]["DocumentsItem"][0], live["DataList"][1]["DocumentsItem"][0]],
        "AuthorsItem": [{"FullName": "Some Author"}],
        "FedCitesItem": [{"Citation": "77 FR 12345"}],
    }
    flattened = list(docket_sheet_rows(multi))
    assert [row["accession_no"] for row in flattened] == ["20110714-5024", "20110715-3051"]
    assert all(row["AuthorsItem"] == [{"FullName": "Some Author"}] for row in flattened)
    assert all(row["FedCitesItem"] == [{"Citation": "77 FR 12345"}] for row in flattened)
    for bad in ({}, {"DocumentsItem": []}, {"DocumentsItem": ["not a mapping"]}):
        with pytest.raises(FercElibraryError):
            list(docket_sheet_rows(bad))
    for bad in (
        {"category": "Submittal"},
        {"accession_no": ""},
        {"accession_no": "  "},
        {"accession_no": " 20110714-5024"},
        {"accession_no": "not-an-accession"},
    ):
        with pytest.raises(FercElibraryError, match="accession"):
            docket_sheet_document_accession(bad)


def test_docket_sheet_walk_advances_pagenumber_and_keys_accessions():
    """The walk pages by request body: pageNumber 0-based, +1 per full page, declared total holding across pages."""
    transport = Transport(DOCKET_SHEET_P1, DOCKET_SHEET_P2)
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.docket_sheet_pages(sheet_body(page_size=2)))
    assert [len(page.records) for page in pages] == [2, 1]
    assert [page.declared_count for page in pages] == [3, 3]
    assert pages[1].next_body is None
    sent = [json.loads(call.read()) for call in transport.calls]
    assert [body["pageNumber"] for body in sent] == [0, 1]
    assert all(body["dockets"] == "er11-4046" and body["subdockets"] == "001" for body in sent)
    assert transport.calls[0].headers["content-type"] == "application/json"
    assert str(transport.calls[0].url) == DOCKET_SHEET_URL


def test_docket_sheet_reader_yields_documents_and_records_failures():
    """The live 2026-09-25 sheet yields every document field verbatim, keyed by accession; a refusal keys the sheet."""
    transport = Transport(DOCKET_SHEET_LIVE)
    reader = FercDocketSheetReader(FercElibraryReader(budget=BUDGET, transport=transport), "er11-4046", "001")
    documents = list(reader.iter_records())
    live = json.loads(DOCKET_SHEET_LIVE)["DataList"]
    digest = "sha256:" + hashlib.sha256(DOCKET_SHEET_LIVE).hexdigest()
    assert documents == [
        {
            **row["DocumentsItem"][0],
            "AuthorsItem": [],
            "FedCitesItem": [],
            "identity": accession,
            "captureSha256": digest,
        }
        for row, accession in zip(live, ("20110714-5024", "20110715-3051", "20110816-3002"), strict=True)
    ]
    assert {"FERC_CITE", "fed_reg_num", "issued_date", "comments_due_date"} <= set(documents[0])
    assert reader.last_keys == ["20110714-5024", "20110715-3051", "20110816-3002"]
    assert reader.failed_keys == [] and reader.empty_observations == {}
    assert reader.key == "ER11-4046-001"
    assert len(transport.calls) == 1
    sent = json.loads(transport.calls[0].read())
    assert sent["dockets"] == "er11-4046" and sent["subdockets"] == "001" and sent["pageNumber"] == 0
    refused = FercDocketSheetReader(
        FercElibraryReader(budget=BUDGET, transport=Transport(ERROR_LIST_BODY)), "ER11-4046"
    )
    assert list(refused.iter_records()) == []
    assert refused.failed_keys == ["ER11-4046"] and "ErrorList" in refused.failure_reasons["ER11-4046"]
    assert FercDocketSheetReader(FercElibraryReader(budget=BUDGET), "ER11-4046", None).key == "ER11-4046"
    with pytest.raises(CredentialRefusedError):
        list(
            FercDocketSheetReader(
                FercElibraryReader(budget=BUDGET, transport=Transport(b"__401__")), "ER11-4046"
            ).iter_records()
        )


def test_docket_sheet_empty_answer_is_an_observation_with_retry_posture():
    """A zero sheet is the publisher-side bug: a failed key with its timestamp, re-asked until rows arrive."""
    with FercElibraryReader(budget=BUDGET, transport=Transport(DOCKET_SHEET_EMPTY)) as source:
        pages = list(source.docket_sheet_pages(sheet_body()))
    assert len(pages) == 1 and pages[0].records == () and pages[0].declared_count == 0
    assert pages[0].next_body is None
    elibrary = FercElibraryReader(budget=BUDGET, transport=Transport(DOCKET_SHEET_EMPTY, DOCKET_SHEET_LIVE))
    reader = FercDocketSheetReader(elibrary, "ER11-4046", "001")
    assert list(reader.iter_records()) == []
    assert reader.last_keys == [] and reader.failed_keys == ["ER11-4046-001"]
    assert reader.failure_reasons == {"ER11-4046-001": REQUESTED_EMPTY}
    assert "ER11-4046-001" in reader.empty_observations
    documents = list(reader.iter_records())
    assert [document["identity"] for document in documents] == ["20110714-5024", "20110715-3051", "20110816-3002"]
    assert reader.empty_observations == {} and reader.last_keys[-1] == "20110816-3002"


def test_docket_sheet_walk_refusals():
    """A silent or inconsistent end refuses: ErrorList, count drift, mismatch, overserving, page bound, repeats."""
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(sheet_edited(ErrorList=["denied"]))) as source,
        pytest.raises(FercElibraryError, match="ErrorList"),
    ):
        list(source.docket_sheet_pages(sheet_body(page_size=2)))
    drifted = sheet_page(json.loads(DOCKET_SHEET_P1), totalHits=4)
    with FercElibraryReader(budget=BUDGET, transport=Transport(DOCKET_SHEET_P1, drifted)) as source:
        with pytest.raises(DeclaredCountChanged) as changed:
            list(source.docket_sheet_pages(sheet_body(page_size=2)))
        assert (changed.value.declared, changed.value.changed_to) == (3, 4)
    terminal = sheet_page(json.loads(DOCKET_SHEET_P2), totalHits=4)
    first_declares_four = sheet_page(json.loads(DOCKET_SHEET_P1), totalHits=4)
    with FercElibraryReader(budget=BUDGET, transport=Transport(first_declares_four, terminal)) as source:
        with pytest.raises(DeclaredCountMismatch) as mismatch:
            list(source.docket_sheet_pages(sheet_body(page_size=2)))
        assert (mismatch.value.declared, mismatch.value.observed) == (4, 3)
    with (
        FercElibraryReader(
            budget=BUDGET, transport=Transport(sheet_page(json.loads(DOCKET_SHEET_P1), numHits=1))
        ) as source,
        pytest.raises(FercElibraryError, match="more rows"),
    ):
        list(source.docket_sheet_pages(sheet_body(page_size=2)))
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(DOCKET_SHEET_P1)) as source,
        pytest.raises(FercElibraryError, match="page bound reached"),
    ):
        list(source.docket_sheet_pages(sheet_body(page_size=2), max_pages=1))
    rows = json.loads(DOCKET_SHEET_P1)["DataList"]
    duplicated = json.dumps(
        {"DataList": [rows[0], rows[0]], "ErrorList": [], "Page": {"totalHits": 3, "numHits": 2, "pageNumber": 0}}
    ).encode()
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(duplicated)) as source,
        pytest.raises(FercElibraryError, match="repeated accession"),
    ):
        list(source.docket_sheet_pages(sheet_body(page_size=2)))
    with (
        FercElibraryReader(
            budget=BUDGET, transport=Transport(json.dumps({"DataList": [], "ErrorList": []}).encode())
        ) as source,
        pytest.raises(FercElibraryError, match="omitted its Page envelope"),
    ):
        list(source.docket_sheet_pages(sheet_body(page_size=2)))


def moved_and_mismatched(walk):
    """A walk starter, two pages whose total moves, and two pages that end one record short of their total."""
    if walk == "search":
        second = json.dumps({**json.loads(SEARCH_P2), "totalHits": 4}).encode()
        return (
            (lambda source: source.search_pages(search_body())),
            (SEARCH_P1, edited(totalHits=4)),
            (edited(totalHits=4), second),
        )
    first, second = (json.loads(page) for page in (DOCKET_SHEET_P1, DOCKET_SHEET_P2))
    return (
        lambda source: source.docket_sheet_pages(sheet_body(page_size=2)),
        (DOCKET_SHEET_P1, sheet_page(second, totalHits=4)),
        (sheet_page(first, totalHits=4), sheet_page(second, totalHits=4)),
    )


@pytest.mark.parametrize("walk", ["search", "sheet"])
def test_walk_refusals_carry_the_deciding_page_and_the_traversal_counts(walk):
    """A moved total and a terminal disagreement both keep the page they were decided on and the walk's position."""
    start, moved, short = moved_and_mismatched(walk)
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(*moved)) as source,
        pytest.raises(DeclaredCountChanged) as changed,
    ):
        list(start(source))
    assert attached_capture(changed.value).body == moved[1]
    assert changed.value.paged_json_acquisition["operation"] == "traversal"
    assert changed.value.paged_json_acquisition["pageIndex"] == 1
    with (
        FercElibraryReader(budget=BUDGET, transport=Transport(*short)) as source,
        pytest.raises(DeclaredCountMismatch) as mismatch,
    ):
        list(start(source))
    assert attached_capture(mismatch.value).body == short[1]
    context = mismatch.value.paged_json_acquisition
    assert (context["declaredCount"], context["observedCount"], context["pageIndex"]) == (4, 3, 1)


def test_a_caller_supplied_walk_body_is_validated_before_any_request():
    """A page size that is missing, zero or a bool cannot spin a walk to its page bound."""
    transport = Transport()
    with FercElibraryReader(budget=BUDGET, transport=transport) as source:
        for results in (0, None, True, "100", 101):
            with pytest.raises(FercElibraryError, match="resultsPerPage"):
                source.search_pages({**search_body(), "resultsPerPage": results})
        with pytest.raises(FercElibraryError, match="numHits"):
            source.docket_sheet_pages({**sheet_body(), "numHits": 0})
        with pytest.raises(FercElibraryError, match="pageNumber"):
            source.docket_sheet_pages({**sheet_body(), "pageNumber": -1})
    assert transport.calls == []
