"""The CFTC comments portal as a :class:`~spicy_docs.sources.base.Reader`.

One pass yields two record kinds in publisher spellings, walking the portal's
own route grammar: for each requested year, the releases listing yields one
``cftc-release`` record per item, then each release's comment listing yields
one ``cftc-comment`` record per row -- merged with that comment's detail page
when ``fetch_details`` is on, because the letter's file links live only there.
Letter bytes are a separate bounded concern
(:mod:`spicy_docs.sources.cftc_comments.attachments`); this reader records
the files' locators, it does not download them.

Recovery follows the package's fetcher rules:

1. A portal refusal (the Cloudflare edge, or any 401/403) aborts the run as
   :class:`~spicy_docs.sources.cftc_comments.acquisition.CftcPortalRefusedError`;
   it is never recorded as a key that merely failed.
2. Every key whose records could not be fully established -- a listing or
   detail that answered 404/410, refused to parse, or ended mid-walk -- stays
   out of ``last_keys`` and lands on ``failed_keys``, so the next run retries
   it. A release whose listing fails still yields the release record (the
   releases page stated it) but its rule key is failed, because its comments
   were not enumerated.
3. A listing that states its totals must be walked to agreement: pages follow
   the pager's own Next anchors, and a walk refuses rather than settling when
   it repeats a comment, when a page states a total other than the first
   page's, or when it ends with a number of distinct comments other than the
   stated total -- a listing that shifts while it is read can repeat one row
   and skip another while serving exactly its count
   (``docs/sources/listings.md``).
4. Keys are ``rule:{id}`` and ``comment:{id}`` -- the portal's own identities,
   stable across every URL spelling that reaches them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from spicy_docs.sources.base import Reader
from spicy_docs.sources.cftc_comments.acquisition import CftcPageAcquisition, CftcPortalAcquirer
from spicy_docs.sources.cftc_comments.pages import (
    ROWS_PER_PAGE,
    CftcCommentListPage,
    CftcCommentsSourceError,
    comment_list_url,
    releases_url,
)

if TYPE_CHECKING:
    from spicy_docs.sources.cftc_comments.pages import CftcCommentDetail, CftcCommentRow

#: Runaway guard, not a publisher bound: the widest observed listing (the whole
#: portal's comments) stated 6,022 pages of 10 rows on 2025-01-23.
DEFAULT_MAX_LISTING_PAGES = 10_000
DEFAULT_MAX_DETAIL_FAILURES = 10_000


class CftcCommentsReader(Reader):
    """Read one walk's worth of CFTC releases and their comment letters as records.

    After a complete ``iter_records`` pass, ``last_keys`` holds every key whose
    records were fully established and ``failed_keys`` every key that was
    attempted but was not, for the next run to retry. A refusal raises and
    leaves both lists empty for the keys it did not reach -- a run that stops
    early manifests nothing it did not serve.
    """

    def __init__(
        self,
        acquirer: CftcPortalAcquirer,
        *,
        years: Iterable[int],
        fetch_details: bool = True,
        release_type: str | None = None,
        max_listing_pages: int = DEFAULT_MAX_LISTING_PAGES,
        max_detail_failures: int = DEFAULT_MAX_DETAIL_FAILURES,
    ) -> None:
        if not isinstance(acquirer, CftcPortalAcquirer):
            raise TypeError("acquirer must be a CftcPortalAcquirer")
        if isinstance(max_listing_pages, bool) or not isinstance(max_listing_pages, int) or max_listing_pages < 1:
            raise ValueError("max_listing_pages must be a positive integer")
        if isinstance(max_detail_failures, bool) or not isinstance(max_detail_failures, int) or max_detail_failures < 0:
            raise ValueError("max_detail_failures must be a non-negative integer")
        if release_type is not None and (not isinstance(release_type, str) or not release_type.strip()):
            raise ValueError("release_type must be a nonempty trimmed string or None")
        self.acquirer = acquirer
        self.years = tuple(sorted(dict.fromkeys(years)))
        if not self.years:
            raise ValueError("years must name at least one walk year")
        for year in self.years:
            releases_url(year=year)  # refuse an impossible year before any request
        self.fetch_details = fetch_details
        self.release_type = release_type
        self.max_listing_pages = max_listing_pages
        self.max_detail_failures = max_detail_failures
        self._detail_failures = 0
        super().__init__()

    def iter_records(self) -> Iterator[dict]:
        """Yield release and comment records for the walk's years, rules before their comments."""
        self.last_keys, self.failed_keys = [], []
        self._detail_failures = 0
        for year in self.years:
            acquisition = self.acquirer.releases_page(year=year)
            for release in _releases_of(acquisition, self.release_type):
                yield _release_record(release, acquisition)
                yield from self._walk_rule(release.rule_id, release.title)

    def _walk_rule(self, rule_id: int, title: str) -> Iterator[dict]:
        """Yield one record per comment row, merged with its detail when configured.

        The rule key reaches ``last_keys`` only when its listing and every
        requested detail were established; otherwise it lands on
        ``failed_keys`` once, so the next run retries it.
        """
        rule_key = f"rule:{rule_id}"
        try:
            rows = self._listing_rows(rule_id)
        except CftcCommentsSourceError:
            self.failed_keys.append(rule_key)
            return
        rule_settled = True
        for row in rows:
            record = _comment_record(row, title)
            comment_key = f"comment:{row.comment_id}"
            if not self.fetch_details:
                self.last_keys.append(comment_key)
                yield record
                continue
            try:
                detail_acquisition = self.acquirer.view_comment_page(row.comment_id)
                detail = detail_acquisition.page
                if detail.comment_id != row.comment_id or detail.rule_id != rule_id:
                    raise CftcCommentsSourceError("CFTC comment detail does not state this row's identities")
            except CftcCommentsSourceError:
                self._detail_failures += 1
                self.failed_keys.append(comment_key)
                if rule_settled:
                    self.failed_keys.append(rule_key)
                    rule_settled = False
                if self._detail_failures > self.max_detail_failures:
                    raise
                yield record
                continue
            self.last_keys.append(comment_key)
            yield _merged_comment_record(record, detail, detail_sha256=detail_acquisition.sha256)
        if rule_settled:
            self.last_keys.append(rule_key)

    def _listing_rows(self, rule_id: int) -> tuple[CftcCommentRow, ...]:
        """Every distinct comment one rule's listing states, walked by its own Next anchors to its stated total."""
        rows: dict[int, CftcCommentRow] = {}
        stated: int | None = None
        url: str | None = comment_list_url(rule_id)
        for page_index in range(self.max_listing_pages):
            listing = self.acquirer.comment_list_page(url).page
            if not isinstance(listing, CftcCommentListPage):
                raise CftcCommentsSourceError("CFTC comment listing capture did not parse as a listing")
            if page_index == 0:
                stated = listing.total_items
            elif listing.total_items != stated:
                raise CftcCommentsSourceError(
                    f"CFTC comment listing stated {listing.total_items} rows after stating {stated}"
                )
            for row in listing.rows:
                if row.comment_id in rows:
                    raise CftcCommentsSourceError(f"CFTC comment listing repeated comment {row.comment_id}")
                rows[row.comment_id] = row
            url = listing.next_page_url
            if url is None:
                if stated is not None and len(rows) != stated:
                    raise CftcCommentsSourceError(
                        f"CFTC comment listing served {len(rows)} distinct comments of the {stated} it stated"
                    )
                return tuple(rows.values())
        raise CftcCommentsSourceError("CFTC comment listing exceeded its page bound before ending")


def _releases_of(acquisition: CftcPageAcquisition, release_type: str | None):
    page = acquisition.page
    for release in page.releases:
        if release_type is None or (release.release_type or "") == release_type:
            yield release


def _release_record(release, acquisition: CftcPageAcquisition) -> dict:
    return {
        "kind": "cftc-release",
        "key": f"rule:{release.rule_id}",
        "ruleId": release.rule_id,
        "title": release.title,
        "releaseType": release.release_type,
        "frCitation": release.fr_citation,
        "frUrl": release.fr_url,
        "frPdfUrl": release.fr_pdf_url,
        "deadline": release.deadline,
        "openDate": release.open_date,
        "closingDate": release.closing_date,
        "extendedDate": release.extended_date,
        "commentListUrl": release.comment_list_url,
        "releasesPageUrl": acquisition.page.url,
        "releasesPageSha256": acquisition.sha256,
    }


def _comment_record(row, rule_title: str) -> dict:
    return {
        "kind": "cftc-comment",
        "key": f"comment:{row.comment_id}",
        "commentId": row.comment_id,
        "ruleId": row.rule_id,
        "ruleTitle": rule_title,
        "dateReceived": row.date_received,
        "releaseText": row.release_text,
        "firstName": row.first_name,
        "lastName": row.last_name,
        "organizations": list(row.organizations),
        "files": [],
        "detailUrl": None,
        "detailSha256": None,
        "submitter": None,
        "commentDate": None,
        "commentText": None,
        "ruleCitation": None,
    }


def _merged_comment_record(record: dict, detail: CftcCommentDetail, *, detail_sha256: str) -> dict:
    merged = dict(record)
    merged.update(
        {
            "submitter": detail.submitter,
            "commentDate": detail.date,
            "commentText": detail.text,
            "ruleCitation": detail.rule_citation,
            "organizations": list(detail.organizations) or record["organizations"],
            "detailUrl": detail.url,
            "detailSha256": detail_sha256,
            "files": [{"fileId": file.file_id, "fileName": file.file_name, "url": file.url} for file in detail.files],
        }
    )
    return merged


__all__ = ["DEFAULT_MAX_LISTING_PAGES", "ROWS_PER_PAGE", "CftcCommentsReader"]
