"""Keyless, paced capture of SEC comment pages and files under the publisher's fair-access policy.

sec.gov's fair-access policy asks for a declared User-Agent naming the project
with a contact address, at most ten requests a second, and reasonable retries.
This module spells the agent from :func:`declared_user_agent` -- built from
``SPICY_DOCS_CONTACT_EMAIL`` so an operator states a real mailbox -- paces
every request with the shared client's ``min_request_interval_seconds``
(``0.5`` keeps a single-threaded walk an order of magnitude under the stated
ceiling), and inherits the shared client's bounded retries with backoff. An
agent without the declared ``contact:`` shape is refused, so a browser spoof is
never sent, and a live acquirer (no injected transport) refuses the reserved
``.invalid`` placeholder mailbox; sec.gov served every probe on 2026-09-24 to
the declared agent.

Two file kinds come down the same bounded route, each proved from its own
bytes: a PDF must answer ``application/pdf``, begin ``%PDF-`` and end
``startxref N %%EOF`` with ``N`` naming a cross-reference inside the capture. A
linearized PDF may not be shorter than its ``/L``; one longer than ``/L`` holds
an appended revision (ISO 32000-1 table F.1: the hint is then stale) and must
end with a cross-reference at or beyond ``/L``.
An HTM/HTML comment file must answer ``text/html``,
begin as HTML, and state the docket its URL names (both observed shapes say
``File No. S7-11-23``, in the body and in a section document's ``<title>``).
The final URL must equal the locator, so a redirect cannot be read as the file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.pdf_bytes import check_pdf_bytes, linearized_length, terminal_xref_offset
from spicy_docs.sources.sec_comments.pages import (
    COMMENT_EXTENSIONS,
    DEFAULT_MAX_INDEX_PAGES,
    DEFAULT_MAX_LISTING_PAGES,
    MAX_PAGE_BYTES,
    SecCommentListingPage,
    SecCommentSection,
    SecCommentsSourceError,
    SecCommentsUnavailableError,
    SecRulemakingIndexPage,
    SecRulePage,
    check_continuation,
    listing_docket,
    parse_comment_listing_page,
    parse_rule_page,
    parse_rulemaking_index_page,
    rule_page_url,
    rulemaking_index_url,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_payload,
    check_request_count,
    check_timing,
    limit_byte_bound,
    named_challenge,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

#: The complete S7-11-23 capture reached 16,574,487 bytes for one file (receipt
#: scraper-completion-2026-09-24T235248Z/fcc-sec/sec-full). The default covers that sample;
#: the cap is a runaway guard, not a publisher population measurement.
DEFAULT_MAX_COMMENT_BYTES = 16 * 1024 * 1024
MAX_COMMENT_BYTES = 512 * 1024 * 1024
PDF_MEDIA_TYPES = ("application/pdf",)
HTML_MEDIA_TYPES = ("text/html",)
#: sec.gov's policy ceiling is 10 requests/second; 0.5 s keeps one walk far under it.
RECOMMENDED_MIN_REQUEST_INTERVAL_SECONDS = 0.5
CONTACT_EMAIL_ENVVAR = "SPICY_DOCS_CONTACT_EMAIL"
DEFAULT_CONTACT_EMAIL = "sec-comments@example.invalid"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
#: The declared agent's shape, ``name/version (purpose; contact: mailbox)``, with the mailbox captured.
_DECLARED_AGENT = re.compile(r"[^\s/()]+/[^\s()]+ \([^()\r\n]*; contact: ([^@\s()]+@[^@\s()]+\.[^@\s()]+)\)")
#: After an optional BOM and whitespace, an HTML document opens with ``<`` and a letter or ``!``.
_HTML_MAGIC = re.compile(rb"(?:\xef\xbb\xbf)?\s*<[a-zA-Z!]", re.DOTALL)
_HTML_MAGIC_WINDOW = 256


def declared_user_agent(contact_email: str | None = None) -> str:
    """The fair-access User-Agent: project name and a contact mailbox, never a browser spoof.

    The mailbox comes from ``contact_email``, then ``SPICY_DOCS_CONTACT_EMAIL``,
    then a reserved placeholder an operator must replace. It is validated for
    one address shape so a stray newline or space can never travel into a
    request header.
    """
    email = contact_email or os.environ.get(CONTACT_EMAIL_ENVVAR) or DEFAULT_CONTACT_EMAIL
    if not isinstance(email, str) or _EMAIL.fullmatch(email.strip()) is None or email != email.strip():
        raise SecCommentsSourceError(
            f"contact email must be one address like ops@example.org; set {CONTACT_EMAIL_ENVVAR} for real crawls"
        )
    return f"spicy-docs-sec-comments/1.0 (SpicyDocs SEC rulemaking comments; contact: {email})"


def _checked_agent(agent: object, *, live: bool) -> str:
    """Refuse an agent without the declared contact shape, or a live one whose mailbox is a reserved ``.invalid``."""
    declared = _DECLARED_AGENT.fullmatch(agent) if isinstance(agent, str) else None
    if declared is None:
        raise SecCommentsSourceError(
            "user_agent must declare the project and a contact: name/1.0 (purpose; contact: ops@example.org)"
        )
    if live and declared[1].endswith(".invalid"):
        raise SecCommentsSourceError(f"a live SEC crawl needs a real contact mailbox; set {CONTACT_EMAIL_ENVVAR}")
    return agent


class SecCommentsRefusedError(CredentialRefusedError):
    """sec.gov answered 401/403 to the declared agent. A bot wall proves nothing about the files.

    Kept a ``CredentialRefusedError`` subclass on purpose: this route holds no
    credential, but a refusal still ends the operation, so callers that abort
    on one keep aborting. The keyless capture retains the refused body.
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"SEC comments source refused {url}; a refusal is never an observation of absence")
        self.url = url


@dataclass(frozen=True, slots=True)
class SecCommentsBudget:
    """Bounds for each request; pacing persists across one acquirer's whole life."""

    max_requests: int
    max_page_bytes: int
    max_comment_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_page_bytes, "max_page_bytes", MAX_PAGE_BYTES)
        check_byte_bound(self.max_comment_bytes, "max_comment_bytes", MAX_COMMENT_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class SecPageAcquisition:
    """One captured page render and what it stated."""

    page: SecRulemakingIndexPage | SecCommentListingPage | SecRulePage
    capture: CapturedBodyResponse
    request_count: int
    budget: SecCommentsBudget


@dataclass(frozen=True, slots=True)
class SecCommentFileAcquisition:
    """Exact comment-file bytes with the locator they were proved against."""

    url: str
    file_name: str
    format: str
    pdf_version: str | None
    linearized_length: int | None
    capture: CapturedBodyResponse
    request_count: int
    budget: SecCommentsBudget

    @property
    def sha256(self) -> str:
        return self.capture.sha256


def read_comment_file(
    body: bytes,
    *,
    url: str,
    media_type: str | None,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_COMMENT_BYTES,
) -> tuple[str, str | None, int | None]:
    """Prove the bytes are one complete comment file at the locator the listing stated.

    Returns ``(format, pdf_version, linearized_length)``. Identity is the
    request -- a URL a retained listing stated, a final URL equal to it, the
    publisher's media type -- plus the file's own statements: ``%PDF-`` magic,
    its terminal cross-reference and its linearization length; HTML's opening
    tag and the docket its body names for HTM/HTML. The docket check is the publisher's own
    witness: both HTML shapes probed on 2026-09-24 state ``File No. S7-11-23``.
    """
    limit = limit_byte_bound(max_bytes, name="max_bytes", cap=MAX_COMMENT_BYTES, error_type=SecCommentsSourceError)
    docket = listing_docket(url)
    extension = urlsplit(url).path.rsplit(".", 1)[-1].lower()
    if extension not in COMMENT_EXTENSIONS:
        raise SecCommentsSourceError("comment locator names a format this route does not read")
    check_final_url(
        final_url, url, error_type=SecCommentsSourceError, message="SEC comment file final URL differs from its locator"
    )
    body = check_payload(body, limit, label="SEC comment file", error_type=SecCommentsSourceError, allow_empty=False)
    served = bare_media_type(media_type)
    if extension == "pdf":
        if served not in PDF_MEDIA_TYPES:
            raise SecCommentsSourceError("SEC comment PDF is not served as application/pdf")
        version = check_pdf_bytes(body, error_type=SecCommentsSourceError, label="SEC comment PDF")
        length = linearized_length(body)
        if length is not None and len(body) < length:
            raise SecCommentsSourceError("SEC comment PDF is shorter than its stated length; the capture is truncated")
        offset = terminal_xref_offset(body)
        if offset is None:
            raise SecCommentsSourceError("SEC comment PDF does not end with a complete terminal cross-reference")
        if length is not None and offset < length < len(body):
            raise SecCommentsSourceError(
                "SEC comment PDF runs past its stated length without an appended cross-reference"
            )
        return "pdf", version, length
    if served not in HTML_MEDIA_TYPES:
        raise SecCommentsSourceError("SEC comment file is not served as text/html")
    if _HTML_MAGIC.match(body[:_HTML_MAGIC_WINDOW]) is None:
        raise SecCommentsSourceError("SEC comment file does not begin as HTML")
    # The docket, as the URL names it, must appear in the file's own words.
    if docket.lower().encode() not in body.lower():
        raise SecCommentsSourceError("SEC comment file does not state the docket its locator names")
    return extension, None, None


class SecCommentsAcquirer(SourceAcquirer):
    """Keyless capture of index, rule and listing pages, then the files a retained listing stated."""

    def __init__(
        self,
        *,
        budget: SecCommentsBudget,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, SecCommentsBudget):
            raise TypeError("budget must be a SecCommentsBudget")
        self._budget = budget
        agent = _checked_agent(declared_user_agent() if user_agent is None else user_agent, live=transport is None)
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=agent,
            label="SEC comments",
            error_type=SecCommentsSourceError,
            context_key="sec_comments_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> SecCommentsBudget:
        return self._budget

    def _acquire_page(
        self,
        url: str,
        parse: Callable[[CapturedBodyResponse, int], SecRulemakingIndexPage | SecCommentListingPage | SecRulePage],
        *,
        operation: str,
        max_bytes: int | None,
    ) -> SecPageAcquisition:
        limit = narrow_byte_limit(self.budget.max_page_bytes, max_bytes)
        with named_challenge(url, error_type=SecCommentsRefusedError, context_key=self.context_key):
            page, capture = self.capture_validated(
                url,
                media_types=HTML_MEDIA_TYPES,
                parse=parse,
                max_bytes=limit,
                unavailable=SecCommentsUnavailableError,
                context={"operation": operation, "url": url, "maxBytes": limit},
            )
        return SecPageAcquisition(page, capture, self.request_count, self.budget)

    def acquire_rulemaking_index_page(
        self, url: str | None = None, *, page: int | None = None, max_bytes: int | None = None
    ) -> SecPageAcquisition:
        """One GET for one index page; ``url`` defaults to the index's first page."""
        locator = url if url is not None else rulemaking_index_url(page=page)
        return self._acquire_page(
            locator,
            lambda capture, limit: parse_rulemaking_index_page(capture.body, url=locator, max_bytes=limit),
            operation="rulemaking-index-page",
            max_bytes=max_bytes,
        )

    def _walk(
        self, start: str, acquire: Callable[[str], SecPageAcquisition], *, max_pages: int, label: str
    ) -> Iterator[SecPageAcquisition]:
        """Every page from ``start``, following the pager's own next links to its terminal page.

        Refuses to end silently: a repeated continuation, a continuation that
        changes more than ``start``'s ``page`` parameter, a page bound reached
        with a next page outstanding, or a pager that disagrees with the page
        requested each raise, so a walk that returns reached the publisher's
        terminal page. Partial yields stay partial observations.
        """
        check_request_count(max_pages, "max_pages")
        url, seen = start, set()
        for _ in range(max_pages):
            if url in seen:
                raise SecCommentsSourceError(f"{label} pager repeated its continuation")
            seen.add(url)
            acquisition = acquire(url)
            yield acquisition
            if (url := acquisition.page.pager.next_url) is None:
                return
            check_continuation(start, url, label)
        raise SecCommentsSourceError(f"{label} page bound reached before a terminal page")

    def walk_rulemaking_index(
        self, start_url: str | None = None, *, max_pages: int = DEFAULT_MAX_INDEX_PAGES
    ) -> Iterator[SecPageAcquisition]:
        """Every index page from the first (or ``start_url``), by :meth:`_walk`."""
        start = start_url if start_url is not None else rulemaking_index_url()
        return self._walk(start, self.acquire_rulemaking_index_page, max_pages=max_pages, label="SEC rulemaking index")

    def acquire_rule_page(self, url: str, *, max_bytes: int | None = None) -> SecPageAcquisition:
        """Capture a rule page and its stated comment-listing links; fragments name page anchors."""
        locator = rule_page_url(url)
        return self._acquire_page(
            locator,
            lambda capture, limit: parse_rule_page(capture.body, url=locator, max_bytes=limit),
            operation="rule-page",
            max_bytes=max_bytes,
        )

    def acquire_comment_listing_page(self, url: str, *, max_bytes: int | None = None) -> SecPageAcquisition:
        """One GET for one listing page of one docket, as the pager addressed it."""
        return self._acquire_page(
            url,
            lambda capture, limit: parse_comment_listing_page(capture.body, url=url, max_bytes=limit),
            operation="comment-listing-page",
            max_bytes=max_bytes,
        )

    def walk_comment_listing(
        self, url: str, *, max_pages: int = DEFAULT_MAX_LISTING_PAGES
    ) -> Iterator[SecPageAcquisition]:
        """Every page of one docket's listing, by :meth:`_walk`; the locator is checked before any request."""
        listing_docket(url)
        return self._walk(url, self.acquire_comment_listing_page, max_pages=max_pages, label="SEC comment listing")

    def acquire_comment_file(
        self, url: str | None = None, *, section: SecCommentSection | None = None, max_bytes: int | None = None
    ) -> SecCommentFileAcquisition:
        """One bounded GET for one comment or letter-type file a retained listing stated.

        Takes the URL directly, or a ``SecCommentSection`` a parsed listing
        yielded. A 401/403 raises ``SecCommentsRefusedError``; 404/410 raise
        ``SecCommentsUnavailableError``; a body that fails its format or docket
        checks refuses with its bytes retained.
        """
        if section is not None:
            if url is not None:
                raise SecCommentsSourceError("acquire exactly one of url or section")
            locator = section.url
        elif url is None:
            raise SecCommentsSourceError("acquire exactly one of url or section")
        else:
            locator = url
        docket = listing_docket(locator)
        file_name = urlsplit(locator).path.rsplit("/", 1)[-1]
        limit = narrow_byte_limit(self.budget.max_comment_bytes, max_bytes)
        with named_challenge(locator, error_type=SecCommentsRefusedError, context_key=self.context_key):
            read, capture = self.capture_validated(
                locator,
                media_types=tuple(PDF_MEDIA_TYPES + HTML_MEDIA_TYPES),
                parse=lambda response, _limit: read_comment_file(
                    response.body,
                    url=locator,
                    media_type=response.content_type,
                    final_url=response.resolved_url,
                    max_bytes=limit,
                ),
                max_bytes=limit,
                unavailable=SecCommentsUnavailableError,
                context={
                    "operation": "comment-file",
                    "url": locator,
                    "docket": docket,
                    "fileName": file_name,
                    "maxBytes": limit,
                },
            )
        form, pdf_version, linearized_length = read
        return SecCommentFileAcquisition(
            url=locator,
            file_name=file_name,
            format=form,
            pdf_version=pdf_version,
            linearized_length=linearized_length,
            capture=capture,
            request_count=self.request_count,
            budget=self.budget,
        )
