"""CFTC comments portal pages, captures and the walk, offline against pinned fixtures.

Fixtures are trimmed slices of archived and live portal bytes; provenance is
in ``tests/fixtures/cftc_comments/README.md``. The refusal shapes were retained
on 2026-09-24 before later requests succeeded, and complete PDFs are synthetic
where the trailer check needs them. The reader walk tests build minimal listing pages in the
portal's own grammar (parser tests pin that grammar against the real bytes)
because no captured page pairs a listing row with the captured detail's
comment. Letter downloads walk the shared walled-fetch ladder, whose rung
behavior is tested in ``tests/test_walled_fetch.py``; here the ladder is
mocked to prove its answers pass through this route's own gate.
"""

import hashlib
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources import walled_fetch as walled_fetch_module
from spicy_docs.sources.base import Reader
from spicy_docs.sources.cftc_comments.acquisition import (
    BROWSER_USER_AGENT,
    CftcPortalAcquirer,
    CftcPortalBudget,
    CftcPortalRefusedError,
    portal_refusal_kind,
)
from spicy_docs.sources.cftc_comments.attachments import (
    CftcPdfAcquirer,
    CftcPdfError,
    CftcPdfRefusedError,
    CftcPdfUnavailableError,
    PdfBudget,
    PdfLocator,
    pdf_locator,
)
from spicy_docs.sources.cftc_comments.pages import (
    CHANGE_PAGE_PARAM,
    CftcCommentsSourceError,
    CftcCommentsUnavailableError,
    comment_list_url,
    parse_comment_list_page,
    parse_releases_page,
    parse_view_comment_page,
    pdf_url,
    releases_url,
    view_comment_url,
)
from spicy_docs.sources.cftc_comments.reader import CftcCommentsReader
from spicy_docs.sources.walled_fetch import (
    RungOutcome,
    WalledFetchError,
    WalledFetchResult,
)
from spicy_docs.sources.walled_fetch import (
    Transport as LadderTransport,
)
from spicy_docs.transport import capture as capture_module
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cftc_comments"
RELEASES = (FIXTURE_DIR / "releases-2026.html").read_bytes()
LIST_1647 = (FIXTURE_DIR / "comment-list-1647.html").read_bytes()
LIST_P12 = (FIXTURE_DIR / "comment-list-3098-p12.html").read_bytes()
VIEW_59866 = (FIXTURE_DIR / "view-comment-59866.html").read_bytes()
COMMENT_TEXT = (
    "Attached please find FIX Trading Community's comment letter regarding the Request for Comment on the Review "
    "of Swap Data Recordkeeping and Reporting Requirements. RIN 3038–AE12."
)
PDF_HEAD = (FIXTURE_DIR / "comment-letter.pdf.head").read_bytes()
PORTAL_BUDGET = CftcPortalBudget(20, 1024 * 1024, 7, 0)
WALK_BUDGET = CftcPortalBudget(80, 1024 * 1024, 7, 0)
PDF_BUDGET = PdfBudget(20, 1024 * 1024, 7, 0)
BLOCK_PAGE = (
    b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
    b"<body>You are unable to access cftc.gov. Cloudflare Ray ID: a4035ca4e96fc94c</body></html>"
)
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


class Transport(httpx.MockTransport):
    """A mock transport that records calls and answers by URL prefix or exact match."""

    def __init__(self, routes: dict[str, object], default: object = b"no route"):
        self.routes = routes
        self.default = default
        self.calls: list[httpx.Request] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        for route, answer in self.routes.items():
            if url == route or url.startswith(route):
                status, payload, content_type = answer if isinstance(answer, tuple) else (200, answer, "text/html")
                return httpx.Response(status, stream=httpx.ByteStream(payload), headers={"content-type": content_type})
        status, payload, content_type = (
            self.default if isinstance(self.default, tuple) else (200, self.default, "text/html")
        )
        return httpx.Response(status, stream=httpx.ByteStream(payload), headers={"content-type": content_type})


def _synthetic_releases(year: int, rule_id: int, title: str) -> bytes:
    """One minimal releases page in the portal's own grammar."""
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>
\tPublic Comments for {year} - CFTC
</title></head><body>
  <div id="cphContentMain_MainContent_pnlReleaseRepeater"><div class="common-list"><div class="list-release">
    <div class="row">
      <div id="cphContentMain_MainContent_ctl01_rptReleases_pnlLeftColumnWrapper_0" class="column-date">
		1/5/{year}	
</div>
      <div class="column-item">
        <p><span id="cphContentMain_MainContent_ctl01_rptReleases_spanReleaseType_0">Proposed Rule&nbsp;</span>
        <a id="cphContentMain_MainContent_ctl01_rptReleases_hlReleaseLink_0" href="https://www.cftc.gov/LawRegulation/FederalRegister/x.html">79 FR 16689</a></p>
        <p>{title}</p>
        <div id="cphContentMain_MainContent_ctl01_rptReleases_pnlOpenDate_0">\t\tOpen Date:\t\t12/4/2014\t</div>
        <div id="cphContentMain_MainContent_ctl01_rptReleases_pnlClosingDate_0">\t\tClosing Date:\t\t1/5/2015\t</div>
        <div id="cphContentMain_MainContent_ctl01_rptReleases_pnlSubmitViewCommentWrapper_0"><div style="float: right;">
          <a id="cphContentMain_MainContent_ctl01_rptReleases_hlViewComment_0" class="SEOHyperLink" href="CommentList.aspx?id={rule_id}">View Comments</a>
        </div></div>
      </div>
    </div>
  </div></div></div>
</body></html>
""".encode()


def _synthetic_listing(rule_id: int, comment_id: int) -> bytes:
    """One minimal per-rule listing page in the portal's own RadGrid grammar."""
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Comments for a rule - CFTC</title></head><body>
  <div id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList" class="RadGrid">
  <table class="rgMasterTable" id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList_ctl00">
  <thead><tr>
    <th scope="col" class="rgHeader">Date Received</th><th scope="col" class="rgHeader">Release</th>
    <th scope="col" class="rgHeader">First Name</th><th scope="col" class="rgHeader">Last Name</th>
    <th scope="col" class="rgHeader">Organization</th><th scope="col" class="rgHeader">Edit</th>
  </tr></thead><tbody>
  <tr class="rgRow" id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList_ctl00__0">
\t\t<td>5/27/2014</td><td>a rule</td><td>Courtney</td><td>McGuinn</td><td>FIX Trading Community</td><td>
\t\t<a id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList_ctl00_ctl04_hlViewComment" href="ViewComment.aspx?id={comment_id}" style="display: none;"></a>
\t</td>
\t\t</tr>
  </tbody>
  </table></div>
</body></html>
""".encode()


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


@pytest.fixture(autouse=True)
def resolved_proxies(monkeypatch):
    """Both providers resolve offline: a recovered capture reaches the scripted proxy rungs, never the network."""
    resolved = walled_fetch_module.ProxyFetchers(zyte=object(), firecrawl=object())
    monkeypatch.setattr(walled_fetch_module.ProxyFetchers, "from_environment", classmethod(lambda _cls: resolved))


def test_url_builders_spell_the_publishers_grammar():
    """Builders emit exactly the portal's measured spellings and refuse near-misses."""
    assert releases_url() == "https://comments.cftc.gov/PublicComments/ReleasesWithComments.aspx"
    assert (
        releases_url(year=2026)
        == "https://comments.cftc.gov/PublicComments/ReleasesWithComments.aspx?Type=ListAll&Year=2026"
    )
    assert comment_list_url(1647) == "https://comments.cftc.gov/PublicComments/CommentList.aspx?id=1647"
    assert comment_list_url(1647, page=13) == (
        f"https://comments.cftc.gov/PublicComments/CommentList.aspx?id=1647&{CHANGE_PAGE_PARAM}=13"
    )
    assert view_comment_url(59866) == "https://comments.cftc.gov/PublicComments/ViewComment.aspx?id=59866"
    assert pdf_url(25524) == "https://comments.cftc.gov/Handlers/PdfHandler.ashx?id=25524"
    for call in (
        lambda: releases_url(year=126),
        lambda: comment_list_url(0),
        lambda: comment_list_url(1647, page=0),
        lambda: view_comment_url(-1),
        lambda: pdf_url(0),
    ):
        with pytest.raises(CftcCommentsSourceError):
            call()


def test_releases_page_parses_items_years_and_identity():
    """Each item's rule id comes from its own View Comments anchor; fields keep portal spellings."""
    page = parse_releases_page(RELEASES, url=releases_url(year=2026))
    assert page.stated_year == 2026
    assert page.years_stated == (2026, 2025, 2024)
    assert [release.rule_id for release in page.releases] == [7630, 7631, 7633]
    first = page.releases[0]
    assert first.title == "Agency Information Collection Activities Under OMB Review"
    assert first.release_type == "Public Information Collection"
    assert first.fr_citation == "90 FR 55858"
    assert (
        first.fr_url
        == "https://www.cftc.gov/LawRegulation/FederalRegister/publicinformationcollectionrequirements/2025-21882.html"
    )
    assert first.fr_pdf_url == "https://www.cftc.gov/sites/default/files/2025/12/2025-21882a.pdf"
    assert (first.deadline, first.open_date, first.closing_date) == ("1/5/2026", "12/4/2025", "1/5/2026")
    assert first.comment_list_url == comment_list_url(7630)


def test_releases_page_refuses_wrong_year_error_and_challenge_shapes():
    """A render of another year, the portal's error sentence, and a challenge page all refuse."""
    with pytest.raises(CftcCommentsSourceError, match="not the requested"):
        parse_releases_page(RELEASES, url=releases_url(year=2025))
    with pytest.raises(CftcCommentsSourceError, match="error sentence"):
        parse_releases_page(
            b"<html><body>An error occurred while performing your request. Sorry for any inconvenience.</body></html>",
            url=releases_url(year=2026),
        )
    with pytest.raises(CftcCommentsSourceError, match="no release repeater"):
        parse_releases_page(BLOCK_PAGE, url=releases_url(year=2026))


def test_live_release_titles_stop_at_their_paragraph_and_keep_extended_dates():
    """Live extension and related-release fields stay separate from the item's title."""
    body = (FIXTURE_DIR / "releases-2026-live-details.html").read_bytes()
    page = parse_releases_page(body, url=releases_url(year=2026))
    extended, related = page.releases
    assert extended.rule_id == 7641
    assert extended.title == (
        "CFTC staff seeks comment on the potential measures that may be needed to mitigate risks to either "
        "the DCO, or to participants, in cases where the direct clearing of derivatives is provided to retail traders."
    )
    assert (extended.deadline, extended.closing_date, extended.extended_date) == ("2/27/2026", "2/2/2026", "2/27/2026")
    assert related.rule_id == 7650
    assert related.title == "Agency Information Collection Activities Under OMB Review"
    assert related.extended_date is None
    assert related.fr_citation == "91 FR 9239"
    transport = Transport({releases_url(year=2026): body}, default=_synthetic_listing(7641, 59866))
    with CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=transport) as source:
        record = next(CftcCommentsReader(source, years=(2026,)).iter_records())
    assert record["extendedDate"] == "2/27/2026"
    assert record["title"] == extended.title


def test_release_title_keeps_inline_anchor_text():
    body = _synthetic_releases(2026, 1484, 'Comments on <a href="https://www.cftc.gov/">swaps</a>')
    release = parse_releases_page(body, url=releases_url(year=2026)).releases[0]
    assert release.title == "Comments on swaps"


def test_comment_list_parses_per_rule_rows_without_a_pager():
    """A single-page listing reads its rows and states no pager facts."""
    page = parse_comment_list_page(LIST_1647, url=comment_list_url(1647))
    assert page.rule_id == 1647
    assert [row.comment_id for row in page.rows] == [60622, 60636, 60639, 60640]
    first = page.rows[0]
    assert (first.date_received, first.first_name, first.last_name) == ("02/01/2016", "Jeth", "Lee")
    assert first.organizations == ("Singapore Exchange Derivatives Clearing Limited",)
    assert all(row.rule_id == 1647 for row in page.rows)
    assert page.current_page is None and page.next_page_url is None and page.total_items is None


def test_comment_list_reads_the_seo_pager_and_totals():
    """The pager's own statements: current page, next arithmetic, last page, declared totals.

    This capture is the search-all listing (bare ``?3098`` token), the shape
    whose pager the publisher itself renders with that token preserved.
    """
    url = f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=12"
    page = parse_comment_list_page(LIST_P12, url=url)
    assert page.current_page == 12
    assert page.total_items == 60220 and page.total_pages == 6022
    assert (
        page.next_page_url == f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=13"
    )
    assert (
        page.last_page_url == f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=6022"
    )
    row = page.rows[0]
    assert (row.comment_id, row.date_received, row.first_name, row.last_name) == (112, "01/15/2010", "Nilesh", "Gite")
    assert row.release_text == "75 FR 3281 75 FR 3281"


def test_comment_list_pager_must_agree_with_the_request():
    """A render naming another page, or a Next anchor that does not advance by one, refuses."""
    with pytest.raises(CftcCommentsSourceError, match="not the requested page"):
        parse_comment_list_page(
            LIST_P12, url=f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=11"
        )
    doctored = LIST_P12.replace(b"><span>12</span>", b"><span>20</span>", 1)
    with pytest.raises(CftcCommentsSourceError, match="advance"):
        parse_comment_list_page(
            doctored, url=f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=20"
        )
    with pytest.raises(CftcCommentsSourceError, match="no RadGrid header"):
        parse_comment_list_page(BLOCK_PAGE, url=comment_list_url(1647))


def test_view_comment_parses_labels_files_and_rule_identity():
    """The detail states its own comment number, rule and letter file; identities must agree with the request."""
    detail = parse_view_comment_page(VIEW_59866, url=view_comment_url(59866))
    assert detail.comment_id == 59866 and detail.rule_id == 1484
    assert detail.rule_citation == "79 FR 16689"
    assert detail.submitter == "Courtney McGuinn"
    assert detail.organizations == ("FIX Trading Community",)
    assert detail.date == "5/27/2014"
    assert detail.text == COMMENT_TEXT
    assert [(file.file_id, file.file_name) for file in detail.files] == [(25524, "59866CourtneyMcGuinn.pdf")]
    assert detail.files[0].url == pdf_url(25524)
    with pytest.raises(CftcCommentsSourceError, match="number"):
        parse_view_comment_page(VIEW_59866, url=view_comment_url(59865))


def test_live_comment_file_name_retains_publisher_unicode():
    body = (FIXTURE_DIR / "view-comment-113989-live.html").read_bytes()
    detail = parse_view_comment_page(body, url=view_comment_url(113989))
    assert detail.rule_id == 7639
    assert detail.submitter == "Jiří Król"
    assert detail.text == "AIMA's comments attached."
    assert [(file.file_id, file.file_name, file.url) for file in detail.files] == [
        (35792, "113989JiríKról.pdf", pdf_url(35792))
    ]
    empty_name = body.replace("113989JiríKról.pdf".encode(), b"")
    with pytest.raises(CftcCommentsSourceError, match="no file name"):
        parse_view_comment_page(empty_name, url=view_comment_url(113989))


@pytest.mark.parametrize(
    "inline",
    [
        b'<strong>please</strong> <a href="https://example.org/">find</a>',
        b'<strong>please <a href="https://example.org/">find</a></strong>',
        b'<a href="https://example.org/"><strong>please</strong> find</a>',
    ],
)
def test_comment_text_keeps_inline_text_and_stops_before_the_grid_and_footer(inline):
    body = VIEW_59866.replace(
        b"Attached please find",
        b"Attached " + inline + b"<script>unrelated script</script><style>unrelated style</style>",
    ).replace(b"</body>", b"<footer>unrelated footer</footer></body>")
    detail = parse_view_comment_page(body, url=view_comment_url(59866))
    assert detail.text == COMMENT_TEXT
    assert [file.file_id for file in detail.files] == [25524]


def test_portal_acquirer_captures_pages_with_evidence():
    """Page captures check media type, carry digest evidence and send the named browser agent."""
    transport = Transport({releases_url(year=2026).split("?")[0]: RELEASES})
    with CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=transport) as acquirer:
        acquisition = acquirer.releases_page(year=2026)
    assert acquisition.page.releases[0].rule_id == 7630
    assert acquisition.capture.sha256.startswith("sha256:")
    assert acquisition.request_count == 1
    assert transport.calls[0].headers["user-agent"] == BROWSER_USER_AGENT


def test_portal_acquirer_names_unavailable_and_refused_answers():
    """404/410 is the locator having nothing; a Cloudflare 403 is the edge refusing this client."""
    transport = Transport(
        {
            comment_list_url(9): (404, b"gone", "text/html"),
            comment_list_url(8): (403, BLOCK_PAGE, "text/html"),
            comment_list_url(7): (200, b"<html></html>", "application/json"),
        }
    )
    with CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=transport) as acquirer:
        with pytest.raises(CftcCommentsUnavailableError):
            acquirer.comment_list_page(comment_list_url(9))
        with pytest.raises(CftcPortalRefusedError) as refused:
            acquirer.comment_list_page(comment_list_url(8))
        with pytest.raises(CftcCommentsSourceError, match="Content-Type"):
            acquirer.comment_list_page(comment_list_url(7))
    assert refused.value.refusal_kind == "cloudflare-blocked"
    assert portal_refusal_kind(BLOCK_PAGE) == "cloudflare-blocked"
    assert portal_refusal_kind(b"<html>other</html>") == "unrecognized"
    assert portal_refusal_kind(None) == "unrecognized"


def test_portal_recovery_is_a_bool_and_its_direct_attempt_uses_the_injected_transport():
    """Recovery shares the acquirer's own client, so an injected transport carries its direct attempt."""
    with pytest.raises(TypeError, match="bool"):
        CftcPortalAcquirer(budget=PORTAL_BUDGET, recover_walls="yes")
    transport = Transport({releases_url(year=2026): RELEASES})
    with CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=transport, recover_walls=True) as source:
        acquisition = source.releases_page(year=2026)
    assert acquisition.transport is LadderTransport.DIRECT and acquisition.request_count == 1
    assert transport.calls[0].headers["user-agent"] == BROWSER_USER_AGENT


def _paced_clock(monkeypatch):
    elapsed = [0.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        elapsed[0] += delay

    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", sleep)
    return elapsed, sleeps


def _timed_direct(elapsed, calls, status, body, content_type="text/html"):
    """A direct transport that records when each attempt started and answers one fixed response."""

    def handle(request):
        calls.append(("direct", elapsed[0], str(request.url)))
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})

    return httpx.MockTransport(handle)


def test_portal_recovery_paces_each_rung_and_retains_exact_page_provenance(monkeypatch):
    elapsed, sleeps = _paced_clock(monkeypatch)
    calls = []
    bodies = {releases_url(year=2026): RELEASES, view_comment_url(59866): VIEW_59866}

    def zyte(url, **kwargs):
        calls.append(("zyte", elapsed[0], kwargs["max_bytes"]))
        return _ladder_result(url, body=bodies[url], content_type="text/html")

    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", zyte)
    monkeypatch.setattr(walled_fetch_module, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("unexpected rung"))
    direct = _timed_direct(elapsed, calls, 403, BLOCK_PAGE)
    with CftcPortalAcquirer(budget=CftcPortalBudget(2, 1024**2, 7, 3), transport=direct, recover_walls=True) as source:
        releases = source.releases_page(year=2026, max_bytes=65536)
        detail = source.view_comment_page(59866)
        assert source.request_count == detail.request_count == releases.request_count == 2
    assert [call[:2] for call in calls] == [("direct", 0), ("zyte", 3), ("direct", 6), ("zyte", 9)]
    assert sleeps == [3, 3, 3]
    assert [call[2] for call in calls if call[0] == "zyte"] == [65536, 1024**2]
    assert releases.capture.body == RELEASES and detail.capture.body == VIEW_59866
    assert releases.transport is detail.transport is LadderTransport.ZYTE_HTTP
    assert releases.request_id == detail.request_id == "req-1"
    with pytest.raises(ValueError, match="closed"):
        source.releases_page(year=2026)
    assert len(calls) == 4


@pytest.mark.parametrize("cap", [1, 2])
def test_portal_recovery_stops_at_its_single_request_budget(monkeypatch, cap):
    calls = []

    def blocked(transport):
        def fetch(*_args, **_kwargs):
            calls.append(transport)
            return RungOutcome(transport, "wall", body=BLOCK_PAGE)

        return fetch

    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", blocked(LadderTransport.ZYTE_HTTP))
    monkeypatch.setattr(walled_fetch_module, "_firecrawl_rung", blocked(LadderTransport.FIRECRAWL_RAW))
    direct = Transport({}, default=(403, BLOCK_PAGE, "text/html"))
    with CftcPortalAcquirer(
        budget=CftcPortalBudget(cap, 1024**2, 7, 0), transport=direct, recover_walls=True
    ) as source:
        with pytest.raises(CftcPortalRefusedError) as raised:
            source.releases_page(year=2026)
        assert source.request_count == cap
    assert len(direct.calls) + len(calls) == len(raised.value.rung_outcomes) == cap
    assert raised.value.cftc_portal_acquisition["requestCount"] == cap
    assert raised.value.refused_response.response_bytes == BLOCK_PAGE
    assert raised.value.refusal_kind == "cloudflare-blocked"


@pytest.mark.parametrize(
    ("status", "body", "content_type", "error_type", "message"),
    [
        (404, b"gone", "text/html", CftcCommentsUnavailableError, "404"),
        (410, b"gone", "text/html", CftcCommentsUnavailableError, "410"),
        (
            200,
            b"<html>An error occurred while performing your request</html>",
            "text/html",
            CftcCommentsSourceError,
            "error sentence",
        ),
        (200, b"<html>wrong page</html>", "text/html", CftcCommentsSourceError, "repeater"),
        (200, RELEASES, "application/json", CftcCommentsSourceError, "Content-Type"),
    ],
)
def test_portal_recovery_keeps_source_errors_without_trying_another_provider(
    monkeypatch, status, body, content_type, error_type, message
):
    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", lambda *_a, **_k: pytest.fail("source error retried"))
    direct = Transport({}, default=(status, body, content_type))
    with (
        CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=direct, recover_walls=True) as source,
        pytest.raises(error_type, match=message) as raised,
    ):
        source.releases_page(year=2026)
    assert len(direct.calls) == raised.value.cftc_portal_acquisition["requestCount"] == 1
    assert raised.value.capture.body == raised.value.refused_response.response_bytes == body


@pytest.mark.parametrize(
    ("max_bytes", "final_url", "message"),
    [(10, None, "byte bound"), (None, releases_url(year=2025), "final URL")],
)
def test_portal_recovery_holds_a_proxy_answer_to_the_byte_bound_and_the_exact_locator(
    monkeypatch, max_bytes, final_url, message
):
    def fetch(url, *, before_request, **_kwargs):
        before_request()
        return _ladder_result(url, body=RELEASES, content_type="text/html", final_url=final_url)

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", fetch)
    with (
        CftcPortalAcquirer(budget=PORTAL_BUDGET, recover_walls=True) as source,
        pytest.raises(CftcCommentsSourceError, match=message),
    ):
        source.releases_page(year=2026, max_bytes=max_bytes)


def test_a_comment_quoting_block_page_words_is_the_portals_page_not_a_wall(monkeypatch):
    """A letter that quotes a wall's words still reads on the direct answer; the walk neither escalates nor aborts."""
    quote = b"Just a moment: the captcha said 'Attention Required! | Cloudflare'. "
    quoted = VIEW_59866.replace(b"Attached please find", quote + b"Attached please find", 1)
    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", lambda *_a, **_k: pytest.fail("the portal's page escalated"))
    transport = _walk_routes(listing=_synthetic_listing(1484, 59866), detail=quoted)
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport, recover_walls=True) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert records[1]["commentText"] == quote.decode().strip() + " " + COMMENT_TEXT
    assert reader.last_keys == ["comment:59866", "rule:1484"] and reader.failed_keys == []
    assert len(transport.calls) == 3


def test_pdf_locator_accepts_only_the_handlers_grammar():
    """Locators are the detail page's own links; anything else refuses before a request."""
    assert pdf_locator(pdf_url(25524)).file_id == 25524
    for value in (
        "https://comments.cftc.gov/Handlers/PdfHandler.ashx?id=abc",
        "https://evil.example/Handlers/PdfHandler.ashx?id=1",
        12,
    ):
        with pytest.raises((CftcPdfError, CftcCommentsSourceError)):
            pdf_locator(value)


def _ladder_result(
    url: str,
    *,
    status: int = 200,
    body: bytes = MINIMAL_PDF,
    content_type: str = "application/pdf",
    transport: LadderTransport = LadderTransport.ZYTE_HTTP,
    final_url: str | None = None,
) -> WalledFetchResult:
    return WalledFetchResult(
        body=body,
        status_code=status,
        content_type=content_type,
        final_url=final_url or url,
        transport=transport,
        wall=None,
        request_id="req-1",
    )


def _scripted_ladder(monkeypatch, answer):
    """One scripted walled_fetch charging one request per rung it stands for; records the route's ladder arguments."""

    calls: list[dict] = []

    def fake(url, *, max_bytes, timeout_seconds, max_requests=None, before_request=None, **ladder):
        calls.append(
            {
                "url": url,
                "max_bytes": max_bytes,
                "timeout_seconds": timeout_seconds,
                "max_requests": max_requests,
                "allow_browser": ladder.get("allow_browser", False),
            }
        )
        result = answer(url)
        rungs = {LadderTransport.DIRECT: 1, LadderTransport.ZYTE_HTTP: 2, LadderTransport.FIRECRAWL_RAW: 3}
        for _ in range(rungs[result.transport]):
            before_request()
        return result

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", fake)
    return calls


def test_pdf_acquirer_fetches_through_the_walled_ladder_and_keeps_its_provenance(monkeypatch):
    """The ladder answers; the module's own gate reads the bytes and the acquisition states the rung."""
    calls = _scripted_ladder(monkeypatch, lambda url: _ladder_result(url))
    with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer:
        acquisition = acquirer.acquire_pdf(25524)
    assert acquisition.capture.body == MINIMAL_PDF and acquisition.pdf_version == "1.4"
    assert acquisition.capture.sha256.startswith("sha256:")
    assert acquisition.transport is LadderTransport.ZYTE_HTTP
    assert acquisition.request_count == 2
    assert acquisition.request_id == "req-1"
    assert acquisition.budget is PDF_BUDGET
    assert calls == [
        {
            "url": pdf_url(25524),
            "max_bytes": PDF_BUDGET.max_bytes,
            "timeout_seconds": PDF_BUDGET.timeout_seconds,
            "max_requests": PDF_BUDGET.max_requests,
            "allow_browser": False,
        }
    ]


def test_pdf_acquirer_narrows_the_ladder_byte_cap_and_keeps_its_own_bound(monkeypatch):
    """Byte caps narrow per call, never raise; the gate still refuses a ladder answer over the bound."""
    calls = _scripted_ladder(monkeypatch, lambda url: _ladder_result(url))
    with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer:
        acquisition = acquirer.acquire_pdf(25524, max_bytes=1000)
    assert calls[0]["max_bytes"] == 1000
    assert acquisition.capture.body == MINIMAL_PDF
    calls = _scripted_ladder(monkeypatch, lambda url: _ladder_result(url))
    with (
        CftcPdfAcquirer(budget=PdfBudget(20, len(MINIMAL_PDF) - 1, 7, 0)) as acquirer,
        pytest.raises(CftcPdfError, match="byte bound"),
    ):
        acquirer.acquire_pdf(25524, max_bytes=len(MINIMAL_PDF) - 1)
    assert calls[0]["max_bytes"] == len(MINIMAL_PDF) - 1


def test_pdf_acquirer_paces_each_attempt_and_resets_only_the_operation_count(monkeypatch):
    elapsed, sleeps = _paced_clock(monkeypatch)
    calls = []

    def proxy(url, **_kwargs):
        calls.append(("zyte", elapsed[0]))
        return _ladder_result(url)

    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", proxy)
    direct = _timed_direct(elapsed, calls, 403, BLOCK_PAGE)
    with CftcPdfAcquirer(budget=PdfBudget(2, 1024, 7, 3), transport=direct) as source:
        first = source.acquire_pdf(10)
        second = source.acquire_pdf(10000)
        assert source.request_count == first.request_count == second.request_count == 2
    assert [call[:2] for call in calls] == [("direct", 0), ("zyte", 3), ("direct", 6), ("zyte", 9)]
    assert sleeps == [3, 3, 3]
    with pytest.raises(ValueError, match="closed"):
        source.acquire_pdf(10)
    assert len(calls) == 4


def test_a_letter_quoting_block_page_words_is_the_publishers_file(monkeypatch):
    """A PDF whose bytes quote a wall's words is never read as a wall; the direct answer is the file."""
    letter = MINIMAL_PDF.replace(
        b"<< /Type /Catalog >>", b"<< /Type /Catalog >> % Access Denied captcha Cloudflare Ray ID"
    )
    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", lambda *_a, **_k: pytest.fail("the letter escalated"))
    direct = Transport({}, default=(200, letter, "application/pdf"))
    with CftcPdfAcquirer(budget=PDF_BUDGET, transport=direct) as source:
        acquisition = source.acquire_pdf(25524)
    assert acquisition.transport is LadderTransport.DIRECT and acquisition.capture.body == letter


def test_pdf_acquirer_checks_a_constructed_locator_before_requesting(monkeypatch):
    monkeypatch.setattr(walled_fetch_module, "walled_fetch", lambda *_a, **_k: pytest.fail("invalid locator requested"))
    with CftcPdfAcquirer(budget=PDF_BUDGET) as source:
        with pytest.raises(CftcCommentsSourceError):
            source.acquire_pdf(PdfLocator("https://other.example/Handlers/PdfHandler.ashx?id=1", 1))
        with pytest.raises(CftcPdfError, match="identity"):
            source.acquire_pdf(PdfLocator(pdf_url(1), 2))


@pytest.mark.parametrize("cap", [1, 2])
def test_pdf_acquirer_never_attempts_a_rung_past_its_request_cap(monkeypatch, cap):
    calls = []

    def blocked(transport):
        def fetch(*_args, **_kwargs):
            calls.append(transport)
            return RungOutcome(transport, "wall", body=BLOCK_PAGE)

        return fetch

    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", blocked(LadderTransport.ZYTE_HTTP))
    monkeypatch.setattr(walled_fetch_module, "_firecrawl_rung", blocked(LadderTransport.FIRECRAWL_RAW))
    direct = Transport({}, default=(403, BLOCK_PAGE, "text/html"))
    with CftcPdfAcquirer(budget=PdfBudget(cap, 1024, 7, 0), transport=direct) as acquirer:
        with pytest.raises(CftcPdfRefusedError) as raised:
            acquirer.acquire_pdf(25524)
        assert acquirer.request_count == cap
    assert len(direct.calls) + len(calls) == cap
    assert raised.value.cftc_pdf_acquisition["requestCount"] == cap
    assert raised.value.refused_response.response_bytes == BLOCK_PAGE
    assert "request budget" in str(raised.value.__cause__)


def test_pdf_acquirer_names_unavailable_from_a_clean_404(monkeypatch):
    """A clean 404 through the ladder is the locator having nothing; it is not absence and not a refusal."""
    _scripted_ladder(
        monkeypatch,
        lambda url: _ladder_result(
            url, status=404, body=b"none", content_type="text/html", transport=LadderTransport.DIRECT
        ),
    )
    with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer, pytest.raises(CftcPdfUnavailableError) as unavailable:
        acquirer.acquire_pdf(1)
    assert unavailable.value.capture.status_code == 404
    assert unavailable.value.capture.body == b"none"


def test_pdf_acquirer_names_a_wall_from_ladder_exhaustion(monkeypatch):
    """Every rung found a wall: the refusal carries the wall bytes and names the block-page shape."""
    outcomes = (
        RungOutcome(
            LadderTransport.DIRECT,
            "wall",
            detail="the direct answer is a wall page ('Attention Required! | Cloudflare')",
            body=BLOCK_PAGE,
        ),
        RungOutcome(
            LadderTransport.ZYTE_HTTP, "wall", detail="the answer is a wall page ('Attention Required! | Cloudflare')"
        ),
        RungOutcome(
            LadderTransport.FIRECRAWL_RAW,
            "wall",
            detail="the answer is a wall page ('Attention Required! | Cloudflare')",
        ),
    )

    def exhausted(url, *, before_request, **_kwargs):
        for _ in outcomes:
            before_request()
        raise walled_fetch_module._exhausted(url, outcomes, BLOCK_PAGE)

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", exhausted)
    with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer, pytest.raises(CftcPdfRefusedError) as refused:
        acquirer.acquire_pdf(2)
    assert refused.value.refusal_kind == "cloudflare-blocked"
    assert isinstance(refused.value, CredentialRefusedError)
    assert refused.value.refused_response.response_bytes == BLOCK_PAGE
    assert isinstance(refused.value.__cause__, WalledFetchError)
    assert refused.value.rung_outcomes == refused.value.__cause__.rung_outcomes == outcomes
    assert refused.value.cftc_pdf_acquisition["requestCount"] == 3
    assert refused.value.cftc_pdf_acquisition["operation"] == "comment-letter-pdf"


def test_pdf_acquirer_names_a_publisher_refusal_from_exhausted_401_403_rungs(monkeypatch):
    """Every rung answered 401/403 without wall markers: a refusal, never absence, and no wall is invented."""
    outcomes = tuple(
        RungOutcome(rung, "publisher-refused")
        for rung in (LadderTransport.DIRECT, LadderTransport.ZYTE_HTTP, LadderTransport.FIRECRAWL_RAW)
    )

    def exhausted(url, *, before_request, **_kwargs):
        for _ in outcomes:
            before_request()
        raise walled_fetch_module._exhausted(url, outcomes, None)

    monkeypatch.setattr(walled_fetch_module, "walled_fetch", exhausted)
    with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer, pytest.raises(CftcPdfRefusedError) as refused:
        acquirer.acquire_pdf(2)
    assert refused.value.refusal_kind == "unrecognized"
    assert refused.value.refused_response.unavailable_reason == "publisher-refused"
    assert refused.value.cftc_pdf_acquisition["requestCount"] == 3


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        (BLOCK_PAGE, "cloudflare-blocked"),
        (b"<title>Just a moment...</title>", "cloudflare-blocked"),
        (b"<title>Access Denied</title>", "unrecognized"),
        (b"<html>other</html>", "unrecognized"),
        (None, "unrecognized"),
    ],
)
def test_pages_and_letters_name_the_same_block_page_the_same_way(body, kind):
    """Both routes read the refused bytes through the ladder's one wall vocabulary."""
    errors = (CftcPortalRefusedError(releases_url(year=2026)), CftcPdfRefusedError(pdf_url(1)))
    for error in errors:
        if body is not None:
            error.__dict__["refused_response"] = RefusedResponse(error.url, "transport", body, "text/html", "x")
    assert portal_refusal_kind(body) == errors[0].refusal_kind == errors[1].refusal_kind == kind


def test_pdf_acquirer_refuses_clean_answers_that_are_not_complete_pdfs(monkeypatch):
    """Bytes must be a complete PDF whatever rung carried them; a challenge page wearing 200 refuses, not returns."""
    cases = [
        (b"<html>not a pdf</html>", "application/pdf", "magic"),
        (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n", "application/pdf", "trailer"),
        (MINIMAL_PDF, "text/html", "Content-Type"),
        (b"", "application/pdf", "empty"),
        (MINIMAL_PDF, "application/pdf", "final URL"),
    ]
    for body, content_type, match in cases:
        final_url = "https://other.example/Handlers/PdfHandler.ashx?id=25524" if match == "final URL" else None
        _scripted_ladder(
            monkeypatch,
            lambda url, _b=body, _c=content_type, _f=final_url: _ladder_result(
                url, body=_b, content_type=_c, final_url=_f
            ),
        )
        with CftcPdfAcquirer(budget=PDF_BUDGET) as acquirer, pytest.raises(CftcPdfError, match=match) as refused:
            acquirer.acquire_pdf(25524)
        assert refused.value.refused_response.response_bytes == body
        assert refused.value.refused_response.stage == "source-validation"


def test_real_letter_head_carries_the_publishers_magic():
    """The archived letter head proves the handler serves real PDF bytes, not an HTML shell."""
    assert PDF_HEAD.startswith(b"%PDF-1.4")


def _walk_routes(*, listing: bytes, detail: bytes | None = VIEW_59866, rule_id: int = 1484, year: int = 2014):
    routes = {
        releases_url(year=year).split("?")[0]: _synthetic_releases(year, rule_id, "Swap Data Recordkeeping"),
        comment_list_url(rule_id): listing,
    }
    if detail is not None:
        routes[view_comment_url(59866)] = detail
    return Transport(routes)


def test_reader_merges_detail_into_comment_records_and_manifests_keys():
    """A complete pass manifests rule and comment keys; records carry the portal's own spellings."""
    transport = _walk_routes(listing=_synthetic_listing(1484, 59866))
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release", "cftc-comment"]
    release, comment = records
    assert release["key"] == "rule:1484" and release["releaseType"] == "Proposed Rule"
    assert release["frCitation"] == "79 FR 16689" and release["releasesPageSha256"].startswith("sha256:")
    assert comment["key"] == "comment:59866"
    assert comment["submitter"] == "Courtney McGuinn"
    assert comment["organizations"] == ["FIX Trading Community"]
    assert comment["commentDate"] == "5/27/2014"
    assert comment["commentText"] == COMMENT_TEXT
    assert comment["detailSha256"] == "sha256:" + hashlib.sha256(VIEW_59866).hexdigest()
    assert comment["files"] == [{"fileId": 25524, "fileName": "59866CourtneyMcGuinn.pdf", "url": pdf_url(25524)}]
    assert reader.last_keys == ["comment:59866", "rule:1484"]
    assert reader.failed_keys == []
    assert isinstance(reader, Reader)


def test_reader_retries_failed_detail_keys_and_keeps_their_rows():
    """A detail that answers 404 yields its listing row but stays off the manifest for retry."""
    transport = _walk_routes(listing=_synthetic_listing(1484, 59866), detail=None)
    transport.routes[view_comment_url(59866)] = (404, b"gone", "text/html")
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release", "cftc-comment"]
    assert records[1]["submitter"] is None and records[1]["files"] == []
    assert records[1]["detailSha256"] is None
    assert reader.failed_keys == ["comment:59866", "rule:1484"]
    assert reader.last_keys == []


def test_failed_comment_keeps_its_parent_rule_unsettled_until_a_successful_retry():
    transport = _walk_routes(listing=_synthetic_listing(1484, 59866), detail=None)
    transport.routes[view_comment_url(59866)] = (404, b"gone", "text/html")
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,), max_detail_failures=0)
        with pytest.raises(CftcCommentsSourceError):
            list(reader.iter_records())
        assert reader.failed_keys == ["comment:59866", "rule:1484"]
        assert reader.last_keys == []
        transport.routes[view_comment_url(59866)] = VIEW_59866
        records = list(reader.iter_records())
    assert records[1]["detailSha256"] == "sha256:" + hashlib.sha256(VIEW_59866).hexdigest()
    assert reader.last_keys == ["comment:59866", "rule:1484"]
    assert reader.failed_keys == []


def test_reader_fails_the_rule_key_when_the_listing_answers_404():
    """A listing that answers 404 yields the release record but fails the rule key."""
    transport = _walk_routes(listing=b"gone")
    transport.routes[comment_list_url(1484)] = (404, b"gone", "text/html")
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release"]
    assert reader.failed_keys == ["rule:1484"] and reader.last_keys == []


def test_reader_refuses_a_listing_that_ends_short_of_its_declared_total():
    """A pager that declares more rows than its pages served refuses rather than settling short."""
    short = _synthetic_listing(1484, 59866)
    pager = (
        '<tfoot><tr class="rgPager"><td colspan="7"><table><tbody><tr><td class="rgPagerCell">'
        '<div class="rgWrap rgNumPart"><a class="rgCurrentPage" onclick="return false;" '
        'href="javascript:__doPostBack(&#39;x&#39;,&#39;&#39;)"><span>1</span></a></div>'
        '<div class="rgWrap rgInfoPart"> &nbsp;<strong>2</strong> items in <strong>1</strong> pages'
        "</div></td></tr></tbody></table></td></tr></tfoot>"
    )
    tail = b"  </tbody>\n  </table></div>"
    assert tail in short and pager.encode() not in short
    doctored = short.replace(tail, pager.encode() + b"\n  </tbody>\n  </table></div>")
    transport = Transport(
        {
            releases_url(year=2014).split("?")[0]: _synthetic_releases(2014, 1484, "Swap Data Recordkeeping"),
            comment_list_url(1484): doctored,
        }
    )
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release"]
    assert reader.failed_keys == ["rule:1484"] and reader.last_keys == []


def test_reader_aborts_on_an_edge_refusal_without_manifesting():
    """A portal refusal aborts the run; nothing partial reaches the manifest."""
    transport = Transport({releases_url(year=2026).split("?")[0]: (403, BLOCK_PAGE, "text/html")})
    with CftcPortalAcquirer(budget=PORTAL_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2026,))
        with pytest.raises(CftcPortalRefusedError):
            list(reader.iter_records())
    assert reader.last_keys == [] and reader.failed_keys == []


def test_comment_list_refuses_pager_totals_it_cannot_read():
    """A pager whose totals do not parse refuses; it never silently drops the count check."""
    url = f"https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&{CHANGE_PAGE_PARAM}=12"
    unreadable = LIST_P12.replace(b"<strong>60220</strong>", b"<strong>60,220</strong>")
    with pytest.raises(CftcCommentsSourceError, match="pager totals"):
        parse_comment_list_page(unreadable, url=url)


def test_line_breaks_separate_text_and_organizations():
    """``<br>`` breaks words and organizations apart; a joint letter's raw newlines stay organization breaks."""
    listing = parse_comment_list_page(LIST_1647, url=comment_list_url(1647))
    assert listing.rows[1].organizations == (
        "Electric Power Supply Association",
        "Edison Electric Institute",
        "American Gas Association",
    )
    body = VIEW_59866.replace(b"Attached please find", b"First line.<br />Second line<br>third", 1).replace(
        b"\n                                        FIX Trading Community</span>", b"Org A<br />Org B</span>", 1
    )
    detail = parse_view_comment_page(body, url=view_comment_url(59866))
    assert detail.text.startswith("First line. Second line third FIX Trading Community's")
    assert detail.organizations == ("Org A", "Org B")


def _paged_listing(
    rule_id: int, comment_ids: tuple[int, ...], *, page: int = 1, total: int = 0, pages: int = 1, pager: bool = True
) -> bytes:
    """One page of a per-rule listing, with or without the portal's SEO pager, in its own RadGrid grammar."""
    rows = "".join(
        f'<tr class="rgRow"><td>5/27/2014</td><td>a rule</td><td>A</td><td>B</td><td>Org</td>'
        f'<td><a href="ViewComment.aspx?id={comment_id}"></a></td></tr>'
        for comment_id in comment_ids
    )
    continuation = (
        f'<a title="Next Page" href="CommentList.aspx?id={rule_id}&amp;{CHANGE_PAGE_PARAM}={page + 1}">next</a>'
        if page < pages
        else ""
    )
    footer = (
        f'<tfoot><tr class="rgPager"><td colspan="6"><table><tbody><tr><td class="rgPagerCell">'
        f'<div class="rgWrap rgNumPart"><a class="rgCurrentPage" href="#"><span>{page}</span></a>{continuation}</div>'
        f'<div class="rgWrap rgInfoPart"><strong>{total}</strong> items in <strong>{pages}</strong> pages</div>'
        f"</td></tr></tbody></table></td></tr></tfoot>"
        if pager
        else ""
    )
    return f"""<html><body>
<div id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList" class="RadGrid">
<table class="rgMasterTable" id="ctl00_ctl00_cphContentMain_MainContent_gvCommentList_ctl00">
<thead><tr><th>Date Received</th><th>Release</th><th>First Name</th><th>Last Name</th><th>Organization</th>
<th>Edit</th></tr></thead>{footer}
<tbody>{rows}</tbody></table></div></body></html>""".encode()


def _two_page_walk(first: bytes, second: bytes, *, details: bool = True) -> Transport:
    """Releases, a two-page listing and (optionally) both comments' details; page 2 is routed before its prefix."""
    base = _walk_routes(listing=first, detail=VIEW_59866 if details else None)
    routes = {comment_list_url(1484, page=2): second, **base.routes}
    if details:
        routes[view_comment_url(59867)] = VIEW_59866.replace(b"59866", b"59867")
    return Transport(routes)


def test_reader_walks_a_paged_listing_to_its_stated_total():
    transport = _two_page_walk(
        _paged_listing(1484, (59866,), page=1, total=2, pages=2),
        _paged_listing(1484, (59867,), page=2, total=2, pages=2),
    )
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["key"] for record in records] == ["rule:1484", "comment:59866", "comment:59867"]
    assert all(record["detailSha256"] for record in records[1:])
    assert reader.last_keys == ["comment:59866", "comment:59867", "rule:1484"] and reader.failed_keys == []


@pytest.mark.parametrize(
    ("second", "max_listing_pages"),
    [
        (_paged_listing(1484, (59867,), page=2, total=2, pages=2), 1),  # the page bound ends the walk
        (_paged_listing(1484, (59866,), page=2, total=2, pages=2), 5),  # page 2 repeats page 1's comment
        (_paged_listing(1484, (59867,), page=2, total=3, pages=2), 5),  # the stated total moved mid-walk
    ],
    ids=["page-bound", "repeated-comment", "total-drift"],
)
def test_reader_refuses_a_paged_listing_that_does_not_settle(second, max_listing_pages):
    """A repeat can hide a skip while the row count still matches, so repeats and drift refuse like a short walk."""
    transport = _two_page_walk(_paged_listing(1484, (59866,), page=1, total=2, pages=2), second)
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,), max_listing_pages=max_listing_pages)
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release"]
    assert reader.failed_keys == ["rule:1484"] and reader.last_keys == []


def test_reader_refuses_a_single_page_listing_that_repeats_a_comment():
    """Without stated totals only the repeat itself shows the listing is not one row per comment."""
    transport = _walk_routes(listing=_paged_listing(1484, (59866, 59866), pager=False))
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,))
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == ["cftc-release"]
    assert reader.failed_keys == ["rule:1484"] and reader.last_keys == []


def test_reader_without_details_settles_listing_rows_and_requests_no_detail():
    transport = _two_page_walk(
        _paged_listing(1484, (59866,), page=1, total=2, pages=2),
        _paged_listing(1484, (59867,), page=2, total=2, pages=2),
        details=False,
    )
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,), fetch_details=False)
        records = list(reader.iter_records())
    assert [record["detailSha256"] for record in records[1:]] == [None, None]
    assert reader.last_keys == ["comment:59866", "comment:59867", "rule:1484"]
    assert not any("ViewComment" in str(call.url) for call in transport.calls)


@pytest.mark.parametrize(("release_type", "walked"), [("Proposed Rule", True), ("Final Rule", False)])
def test_reader_walks_only_the_selected_release_type(release_type, walked):
    transport = _walk_routes(listing=_synthetic_listing(1484, 59866))
    with CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer:
        reader = CftcCommentsReader(acquirer, years=(2014,), release_type=release_type)
        records = list(reader.iter_records())
    assert [record["kind"] for record in records] == (["cftc-release", "cftc-comment"] if walked else [])
    assert len(transport.calls) == (3 if walked else 1)


def test_reader_refuses_an_impossible_year_before_any_request():
    transport = Transport({})
    with (
        CftcPortalAcquirer(budget=WALK_BUDGET, transport=transport) as acquirer,
        pytest.raises(CftcCommentsSourceError, match="year"),
    ):
        CftcCommentsReader(acquirer, years=(2014, 126))
    assert transport.calls == []
