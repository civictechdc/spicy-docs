"""SEC rule pages discover listings, which state the files captured with their evidence.

``iter_records`` walks one docket's comment listing to its terminal page, then
captures each file that listing stated -- comments and letter-type sections
alike -- yielding one record per file with its exact bytes, the digest of the
listing render that stated it, and the publisher's own row fields. Every
listing render captured, including those before a walk failed, stays on
``listing_pages`` so the caller can retain the bytes each digest names. Keys are
file URLs: after a complete pass ``last_keys`` holds exactly the URLs whose
bytes were captured, so a caller manifests those and nothing else, while
``failed_keys`` holds every URL attempted without success -- a listing page
that answered 404, a walk that refused, a file that failed its format checks
-- for the next run to retry. ``processed_keys`` feeds the previous run's
``last_keys`` back in and skips those files, which is what makes a resume
cheaper than a first pass.

A docket whose derived listing URL answers 404 is recorded and skipped, never
read as zero comments: the rulemaking may have no comment file open, or its
file number may not follow the measured grammar. A refusal (401/403) raises
and ends the pass, per the repository's fetcher rules; records already
yielded stay partial observations, and nothing already captured is lost from
``last_keys``. Identity and dedup key for a file is its absolute URL, the only
spelling the publisher guarantees; a listing that shifts under a walk can
serve one file's row on two pages, and it is captured once.

``rule_urls`` selects publisher-stated discovery: each rule page's received-
comments links are followed, including pages whose index row states no file
number. ``dockets`` keeps the legacy derived-listing route. The two selections
are explicit alternatives. Rule captures and discovery outcomes remain
available even if a page offers no link; that observation never means there
are no comments. A listing two selections state is walked once per pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from spicy_docs.sources.base import Reader
from spicy_docs.sources.sec_comments.acquisition import (
    SecCommentsAcquirer,
    SecCommentsUnavailableError,
    SecPageAcquisition,
)
from spicy_docs.sources.sec_comments.pages import (
    DEFAULT_MAX_LISTING_PAGES,
    SecCommentFile,
    SecCommentListingPage,
    SecCommentSection,
    SecCommentsSourceError,
    comment_index_url,
    rule_page_url,
)
from spicy_docs.transport.credentials import failure_reason
from spicy_docs.transport.source_acquirer import check_request_count


class SecCommentsReader(Reader):
    """Reads every comment file of selected SEC rulemaking dockets, with exact bytes and evidence.

    A metadata-only pass over the listings is the acquirer's
    ``walk_comment_listing``; this reader always captures file bodies, because
    ``last_keys`` means "bytes the caller may manifest".
    """

    def __init__(
        self,
        *,
        acquirer: SecCommentsAcquirer,
        dockets: Iterable[str] | None = None,
        rule_urls: Iterable[str] | None = None,
        max_listing_pages: int = DEFAULT_MAX_LISTING_PAGES,
        processed_keys: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(acquirer, SecCommentsAcquirer):
            raise TypeError("acquirer must be a SecCommentsAcquirer")
        if (dockets is None) == (rule_urls is None):
            raise ValueError("select exactly one of dockets or rule_urls")
        selection = dockets if dockets is not None else rule_urls
        names = list(selection) if not isinstance(selection, str) else []
        if not names or not all(isinstance(name, str) and name.strip() for name in names):
            raise ValueError("dockets or rule_urls must be a nonempty sequence of source locators")
        check_request_count(max_listing_pages, "max_listing_pages")
        self.acquirer = acquirer
        self.dockets = names if dockets is not None else []
        self.rule_urls = list(dict.fromkeys(rule_page_url(url) for url in names)) if rule_urls is not None else []
        self.max_listing_pages = max_listing_pages
        self.processed_keys = frozenset(processed_keys or ())
        #: Every attempted URL that produced no record this pass, with its reason (scrubbed, then truncated).
        self.failures: list[dict[str, str]] = []
        #: Retain these exact rule and listing renders alongside the file evidence.
        self.rule_pages: list[SecPageAcquisition] = []
        self.listing_pages: list[SecPageAcquisition] = []
        self.discovery_outcomes: list[dict] = []
        super().__init__()

    def iter_records(self) -> Iterator[dict]:
        """Yield one record per captured file; ``last_keys``/``failed_keys`` settle as the pass runs."""
        self.last_keys, self.failed_keys, self.failures = [], [], []
        self.rule_pages, self.listing_pages, self.discovery_outcomes = [], [], []
        seen: set[str] = set()
        walked: set[str] = set()
        for listing_url, rule in self._selected_listings():
            if listing_url in walked:
                continue
            walked.add(listing_url)
            pages: list[SecPageAcquisition] = []
            try:
                for page in self.acquirer.walk_comment_listing(listing_url, max_pages=self.max_listing_pages):
                    pages.append(page)
                    self.listing_pages.append(page)
            except SecCommentsUnavailableError as error:
                # Requested and answered: no listing lives at that locator. An observation
                # about the derived URL, never that the docket has no comments.
                self._fail(error.capture.requested_url, f"listing page answered HTTP {error.capture.status_code}")
                continue
            except SecCommentsSourceError as error:
                capture = getattr(error, "capture", None)
                self._fail(capture.requested_url if capture is not None else listing_url, failure_reason(error))
                continue
            yield from self._docket_records(pages, rule, seen)

    def _selected_listings(self) -> Iterator[tuple[str, SecPageAcquisition | None]]:
        for docket in self.dockets:
            yield comment_index_url(docket), None
        for url in self.rule_urls:
            try:
                rule = self.acquirer.acquire_rule_page(url)
            except SecCommentsUnavailableError as error:
                self._fail(error.capture.requested_url, f"rule page answered HTTP {error.capture.status_code}")
                continue
            except SecCommentsSourceError as error:
                self._fail(url, failure_reason(error))
                continue
            self.rule_pages.append(rule)
            listings = rule.page.comment_listing_urls
            self.discovery_outcomes.append(
                {
                    "rule_page_url": rule.page.url,
                    "rule_page_sha256": rule.capture.sha256,
                    "comment_listing_urls": listings,
                    "outcome": "links-stated" if listings else "no-listing-link-stated",
                }
            )
            for listing in listings:
                yield listing, rule

    def _docket_records(
        self, pages: list[SecPageAcquisition], rule: SecPageAcquisition | None, seen: set[str]
    ) -> Iterator[dict]:
        for page_acquisition in pages:
            page = page_acquisition.page
            listing_sha256 = page_acquisition.capture.sha256
            for section in page.sections:
                yield from self._file_record(
                    page, listing_sha256, "sec-comment-section", section.url, section.label, None, seen, rule
                )
            for comment in page.comments:
                yield from self._file_record(
                    page, listing_sha256, "sec-comment", comment.url, comment.link_text, comment, seen, rule
                )

    def _file_record(
        self,
        page: SecCommentListingPage,
        listing_sha256: str,
        kind: str,
        url: str,
        link_text: str,
        stated: SecCommentFile | SecCommentSection | None,
        seen: set[str],
        rule: SecPageAcquisition | None,
    ) -> Iterator[dict]:
        if url in seen:
            return
        seen.add(url)
        if url in self.processed_keys:
            return
        try:
            acquisition = self.acquirer.acquire_comment_file(url=url)
        except SecCommentsUnavailableError as error:
            self._fail(error.capture.requested_url, f"file answered HTTP {error.capture.status_code}")
            return
        except SecCommentsSourceError as error:
            self._fail(url, failure_reason(error))
            return
        self.last_keys.append(url)
        yield {
            "kind": kind,
            "docket": page.docket,
            "rule_title": page.title,
            "listing_url": page.url,
            "listing_sha256": listing_sha256,
            "listing_discovery": "publisher-stated" if rule is not None else "derived-file-number",
            "rule_page_url": rule.page.url if rule is not None else None,
            "rule_page_sha256": rule.capture.sha256 if rule is not None else None,
            "url": url,
            "file_name": acquisition.file_name,
            "format": acquisition.format,
            "link_text": link_text,
            "letter_type": stated.letter_type if isinstance(stated, SecCommentFile) else None,
            "date": stated.date if isinstance(stated, SecCommentFile) else None,
            "captured_at": acquisition.capture.observed_at,
            "content_type": acquisition.capture.content_type,
            "byte_size": acquisition.capture.byte_size,
            "body_sha256": acquisition.sha256,
            "pdf_version": acquisition.pdf_version,
            "linearized_length": acquisition.linearized_length,
            "body": acquisition.capture.body,
        }

    def _fail(self, url: str, reason: str) -> None:
        self.failed_keys.append(url)
        self.failures.append({"url": url, "reason": reason})
