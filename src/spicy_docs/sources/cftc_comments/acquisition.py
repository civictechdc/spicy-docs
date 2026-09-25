"""Bounded capture of CFTC comment-portal pages with optional wall recovery.

Direct acquisition and injected HTTPX transports remain supported. A caller
may select ``recover_walls=True`` to use the shared raw-byte ladder
(:meth:`~spicy_docs.transport.source_acquirer.SourceAcquirer.capture_walled`):
this acquirer's own client, then Zyte HTTP, then Firecrawl rawBase64, every
attempt on the same request budget and pacing clock. A page carrying the
portal's own content placeholder is the publisher's answer, so a comment that
quotes a block-page phrase never reads as a wall. The source still checks the
final URL, byte bound, media type and page shape; a clean publisher error page
never triggers another rung.

The portal's direct route was intermittently walled during the retained
2026-09-24 campaigns. Exhausted recovery raises ``CftcPortalRefusedError``
with the ladder outcomes and bounded refusal evidence; it never establishes
that a page or its comments are absent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from spicy_docs.sources.cftc_comments.pages import (
    HTML_MEDIA_TYPE,
    MAX_PAGE_BYTES,
    CftcCommentDetail,
    CftcCommentListPage,
    CftcCommentsSourceError,
    CftcCommentsUnavailableError,
    CftcReleasesPage,
    comment_list_url,
    is_portal_page,
    parse_comment_list_page,
    parse_releases_page,
    parse_view_comment_page,
    releases_url,
    view_comment_url,
)
from spicy_docs.sources.regulations_gov.attachments import BROWSER_USER_AGENT
from spicy_docs.sources.walled_fetch import Transport, detect_wall
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    limit_byte_bound,
    named_challenge,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

type PortalRefusalKind = Literal["cloudflare-blocked", "unrecognized"]


def portal_refusal_kind(body: bytes | None) -> PortalRefusalKind:
    """Which refusal the retained bytes are, read through the ladder's one wall vocabulary; never an absence."""
    wall = detect_wall(body, refusal=True) if body else None
    return "cloudflare-blocked" if wall is not None and wall.family == "cloudflare" else "unrecognized"


class CftcPortalRefusedError(CredentialRefusedError):
    """The edge in front of the portal refused this client; never an observation about a page.

    A ``CredentialRefusedError`` subclass on purpose: this route holds no
    credential, but a refusal still ends the operation, so callers that abort
    on one keep aborting. ``refusal_kind`` names the block-page shape read from
    the refused bytes on ``refused_response``.
    """

    subject = "comments portal"

    def __init__(self, url: str) -> None:
        super().__init__(
            f"CFTC {self.subject} refused {url}: an access decision about this client, "
            "not an observation that the locator has nothing"
        )
        self.url = url

    @property
    def refusal_kind(self) -> PortalRefusalKind:
        refused = getattr(self, "refused_response", None)
        return portal_refusal_kind(getattr(refused, "response_bytes", None))


@dataclass(frozen=True, slots=True)
class CftcPortalBudget:
    """Bounds for each page request; pacing persists across the client's captures."""

    max_requests: int
    max_page_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_page_bytes, "max_page_bytes", MAX_PAGE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class CftcPageAcquisition:
    """One parsed page with its exact evidence and the budget that bounded it."""

    page: CftcReleasesPage | CftcCommentListPage | CftcCommentDetail
    capture: CapturedBodyResponse
    request_count: int
    budget: CftcPortalBudget
    transport: Transport | None = None
    request_id: str | None = None

    @property
    def sha256(self) -> str:
        return self.capture.sha256


class CftcPortalAcquirer(SourceAcquirer):
    """Keyless, paced capture of one portal page per call, parsed and evidenced.

    One ``max_requests`` budget bounds each capture call; pacing persists
    until ``close``, so a walk through this acquirer stays polite across its
    whole run. An injected ``transport`` carries the direct request, recovered
    or not.
    """

    def __init__(
        self,
        *,
        budget: CftcPortalBudget,
        user_agent: str = BROWSER_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        recover_walls: bool = False,
    ) -> None:
        if not isinstance(budget, CftcPortalBudget):
            raise TypeError("budget must be a CftcPortalBudget")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a nonempty string")
        if not isinstance(recover_walls, bool):
            raise TypeError("recover_walls must be a bool")
        self._budget = budget
        self._recover_walls = recover_walls
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=user_agent,
            label="CFTC comments portal",
            error_type=CftcCommentsSourceError,
            context_key="cftc_portal_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> CftcPortalBudget:
        return self._budget

    def _capture_page(
        self,
        url: str,
        parse: Callable[..., CftcReleasesPage | CftcCommentListPage | CftcCommentDetail],
        *,
        operation: str,
        max_bytes: int | None,
    ) -> CftcPageAcquisition:
        """One page through the direct client or, with ``recover_walls``, the shared ladder; ``parse`` reads its bytes."""
        limit = self.budget.max_page_bytes
        if max_bytes is not None:
            bound = limit_byte_bound(
                max_bytes, name="max_bytes", cap=MAX_PAGE_BYTES, error_type=CftcCommentsSourceError
            )
            limit = min(limit, bound)

        def read(
            response: CapturedBodyResponse, bound: int
        ) -> CftcReleasesPage | CftcCommentListPage | CftcCommentDetail:
            return parse(response.body, url=url, max_bytes=bound)

        request = {
            "media_types": (HTML_MEDIA_TYPE,),
            "parse": read,
            "max_bytes": limit,
            "unavailable": CftcCommentsUnavailableError,
            "context": {"operation": operation, "url": url, "maxBytes": limit},
        }
        if self._recover_walls:
            page, capture, answer = self.capture_walled(
                url, **request, publisher_page=is_portal_page, refusal=CftcPortalRefusedError
            )
            return CftcPageAcquisition(
                page, capture, self.request_count, self.budget, answer.transport, answer.request_id
            )
        with named_challenge(url, error_type=CftcPortalRefusedError, context_key=self.context_key):
            page, capture = self.capture_validated(url, **request)
        return CftcPageAcquisition(page=page, capture=capture, request_count=self.request_count, budget=self.budget)

    def releases_page(self, *, year: int | None = None, max_bytes: int | None = None) -> CftcPageAcquisition:
        """Capture and read one releases listing: the upcoming deadlines, or one year's releases."""
        return self._capture_page(
            releases_url(year=year), parse_releases_page, operation="releases-page", max_bytes=max_bytes
        )

    def comment_list_page(self, url: str, *, max_bytes: int | None = None) -> CftcPageAcquisition:
        """Capture and read one comment-listing page, or one page of its pager."""
        return self._capture_page(url, parse_comment_list_page, operation="comment-list-page", max_bytes=max_bytes)

    def view_comment_page(self, comment_id: int, *, max_bytes: int | None = None) -> CftcPageAcquisition:
        """Capture and read one comment's detail page."""
        return self._capture_page(
            view_comment_url(comment_id), parse_view_comment_page, operation="view-comment-page", max_bytes=max_bytes
        )

    def comment_list_page_for(
        self, rule_id: int, *, page: int | None = None, max_bytes: int | None = None
    ) -> CftcPageAcquisition:
        """One rule's comment listing by identity, spelled by the walk's own builder."""
        return self.comment_list_page(comment_list_url(rule_id, page=page), max_bytes=max_bytes)
