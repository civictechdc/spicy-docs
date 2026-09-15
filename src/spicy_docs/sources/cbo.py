"""CBO cost estimates: the per-Congress XML feeds, and what the bot wall refuses.

The feed CBO advertises, ``www.cbo.gov/cost-estimates/xml``, is behind a
DataDome bot wall and has never answered a raw-byte request: HTTP 403 with
``x-datadome: protected``, to a plain client and a current-Chrome user agent
alike, and the cookie the wall itself sets changes nothing. RefSpec saw the
same wall on 2026-08-04, this module on 2026-09-14. The wall is path-scoped and
also covers ``/publication/<id>`` — the link every item states — and every PDF
path, so the estimate **document** has no keyless route either. ``403`` here is
named a challenge, not a credential refusal: this family holds no credential.

**No header set reaches the documents; only a browser-backed transport could.**
Re-probed 2026-09-14 (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-14/q3-cbo-bot-wall``)
with a complete browser-like request — Chrome 140 user agent, ``Accept``,
``Accept-Language``, ``Referer``, ``Upgrade-Insecure-Requests`` and the three
``Sec-Fetch-*`` headers — the estimate PDF, the advertised XML feed and the
publication page each answered the identical ``403``, 767 bytes,
``server: DataDome``, ``x-datadome: protected``, while the per-Congress feed
answered ``200`` and 431,257 bytes to that same client. So the headers are not
what is refused and the wall is path-scoped, not client-scoped. The 767 bytes
are a JavaScript challenge (``Please enable JS``, a DataDome ``dd`` blob with a
per-response ``cid``): passing it requires executing that script, which no
header can do. No keyless route to an estimate document exists, and none is
stated: the feed's ``<Link>`` is a publication page, and the only hosts CBO's
own retained markup names for documents are ``www.cbo.gov`` paths —
``/system/files/*`` and ``/sites/default/files/*``, both walled. There is no CDN
or ``files``/``static`` host to fall back to. ``acquire_estimate_document``
therefore needs a browser-backed ``transport`` injected by the caller (see
``sources/zyte.py``); this module does not and will not try to solve the
challenge.

One tier answers keyless: ``www.cbo.gov/rss/{congress}congress-cost-estimates.xml``,
one file per Congress. Its shape is CBO's own XML, **not RSS 2.0** — a
``<response>`` root of ``<item key="N">`` elements carrying exactly ``Title``,
``Date``, ``Link``, ``Description`` and ``Bill_Number``, with no channel header
and no namespace. Topic labels, budget-function codes, UMRA mandate flags and
the PAYGO flag are **not** in these bytes; they appear only in RefSpec's
acknowledged reconstruction of the walled feed, never in a verified capture. An
unknown child element refuses the whole feed, so the day CBO publishes one it is
visible instead of silently dropped.

A per-Congress feed is that Congress to date, newest first — the 119th spans
2025-01-10 to 2026-09-11 — and behaved as append-only over a 41-day gap. It is
an observation, never a catalog. A Congress with no file answers 404 with a
Drupal HTML page: requested-empty, not absence of the route.

Byte counts, digests and the measurements behind every claim here:
``docs/sources/cbo.md``,
``corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14/README.md`` and
``corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-14/q3-cbo-bot-wall/README.md``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.reading.xml import scan_xml
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

CBO_COST_ESTIMATES_FEED_URL = "https://www.cbo.gov/cost-estimates/xml"
CBO_PER_CONGRESS_FEED_TEMPLATE = "https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml"
CBO_PUBLICATION_URL_PREFIX = "https://www.cbo.gov/publication/"
CBO_HOST = "www.cbo.gov"

DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_FEED_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
MAX_FEED_ITEMS = 20_000
PDF_MAGIC = b"%PDF-"

FEED_MEDIA_TYPES = ("text/xml", "application/xml", "application/rss+xml")
DOCUMENT_MEDIA_TYPES = ("application/pdf",)

_ITEM_FIELDS = ("Title", "Date", "Link", "Description", "Bill_Number")
_PUBLICATION_ID = re.compile(r"[1-9][0-9]{0,8}")


class CboSourceError(ValueError):
    """The response cannot establish a CBO cost-estimate observation."""


class CboUnavailableError(CboSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"CBO source answered HTTP {capture.status_code}")
        self.capture = capture


class CboChallengeError(CboSourceError):
    """cbo.gov answered a bot challenge; the route has no keyless bytes today.

    This family is keyless, so the shared client retains the refusal body and it
    arrives here on ``refused_response``: 767 bytes through plain HTTPX and 770
    through this module on 2026-09-14. The challenge carries a per-response
    nonce, so its length varies slightly and its digest differs every time -- it
    can be retained but never pinned. Reaching a document past this wall needs a
    browser-backed ``transport``, not a retry.
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"CBO answered a bot challenge for {url}; no keyless bytes are available")
        self.url = url


@dataclass(frozen=True, slots=True)
class CboEstimateItem:
    """One listed estimate exactly as CBO spelled it.

    ``index`` is the position in document order, which CBO's own ``key``
    attribute must equal; the two are one value, so only one is kept. It is a
    position in *that capture*, never an identity: two captures of the 119th
    feed nine hours apart on 2026-09-14 held the same 1,192 items with every
    field byte-identical and both strictly newest-first, yet differed at 76
    positions -- every one a swap inside a run of items sharing one ``Date``.
    Only ``publication_id`` identifies an item across captures, and a changed
    feed digest is not evidence the feed changed.
    ``publication_id`` is the digits of the canonical ``Link``. ``description``
    and ``bill_number`` are ``None`` when the publisher's element is empty,
    which is a real value for procedural items such as the weekly House
    suspension-calendar notices, not drift. Surrounding whitespace is trimmed;
    interior text, including CBO's line breaks, stays verbatim.
    """

    index: int
    publication_id: str
    title: str
    date: str
    link: str
    description: str | None
    bill_number: str | None


@dataclass(frozen=True, slots=True)
class CboCostEstimatesFeed:
    """A feed carries no channel header of its own; the items are the document."""

    items: tuple[CboEstimateItem, ...]


def cbo_cost_estimates_feed_locator() -> str:
    return CBO_COST_ESTIMATES_FEED_URL


def cbo_per_congress_feed_locator(congress: int) -> str:
    """One Congress's feed. CBO numbers Congresses; 116 through 119 are pinned."""
    if isinstance(congress, bool) or not isinstance(congress, int) or not 1 <= congress <= 999:
        raise CboSourceError("congress must be an integer from 1 to 999")
    return CBO_PER_CONGRESS_FEED_TEMPLATE.format(congress=congress)


def cbo_estimate_document_locator(url: str) -> str:
    """An estimate PDF on cbo.gov. No keyless route states one; a caller supplies it."""
    parts = urlsplit(url if isinstance(url, str) else "")
    if (
        parts.scheme != "https"
        or parts.hostname != CBO_HOST
        or parts.port is not None
        or parts.query
        or parts.fragment
        or not parts.path.casefold().endswith(".pdf")
        or ".." in parts.path
        or "//" in parts.path
    ):
        raise CboSourceError("estimate document must be an https://www.cbo.gov/... .pdf URL without a query")
    return url


def _publication_id(link: str) -> str:
    if not link.startswith(CBO_PUBLICATION_URL_PREFIX):
        raise CboSourceError("CBO feed item Link is not a canonical publication URL")
    identifier = link.removeprefix(CBO_PUBLICATION_URL_PREFIX)
    if not _PUBLICATION_ID.fullmatch(identifier):
        raise CboSourceError("CBO feed item Link does not name a publication")
    return identifier


class _FeedScan:
    """Collect items without retaining a tree.

    Measured on the largest real feed (118th Congress, 560,335 bytes, 1,533
    items): streaming and a full tree take the same median time, 5.8 ms against
    5.6 ms, while peak allocation falls from 2,195 KiB to 961 KiB.
    """

    def __init__(self) -> None:
        self.items: list[CboEstimateItem] = []
        self.depth = 0
        self._fields: dict[str, str] = {}
        self._key: str | None = None
        self._parts: list[str] | None = None
        self._field = ""

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        self.depth += 1
        if self.depth == 1:
            if tag != "response":
                raise CboSourceError("CBO feed root element is not <response>")
        elif self.depth == 2:
            if tag != "item":
                raise CboSourceError("CBO feed lists a child of <response> that is not <item>")
            if len(self.items) >= MAX_FEED_ITEMS:
                raise CboSourceError("CBO feed lists more items than supported")
            if set(attributes) != {"key"}:
                raise CboSourceError("CBO feed item requires exactly a key attribute")
            self._key, self._fields = attributes["key"], {}
        elif self.depth == 3:
            if tag not in _ITEM_FIELDS:
                raise CboSourceError(f"CBO feed item carries an unknown field {tag}")
            if tag in self._fields:
                raise CboSourceError(f"CBO feed item repeats {tag}")
            self._field, self._parts = tag, []
        else:
            raise CboSourceError("CBO feed nests an item field")

    def data(self, text: str) -> None:
        if self._parts is not None:
            self._parts.append(text)

    def end(self, _tag: str) -> None:
        if self.depth == 3 and self._parts is not None:
            self._fields[self._field] = "".join(self._parts).strip()
            self._parts = None
        elif self.depth == 2:
            self.items.append(self._item())
        self.depth -= 1

    def _item(self) -> CboEstimateItem:
        index = len(self.items)
        key = self._key or ""
        if not key.isascii() or not key.isdecimal() or int(key) != index:
            raise CboSourceError("CBO feed item key is not its position in document order")
        missing = [name for name in ("Title", "Date", "Link") if not self._fields.get(name)]
        if missing:
            raise CboSourceError("CBO feed item requires a nonempty " + ", ".join(missing))
        link = self._fields["Link"]
        return CboEstimateItem(
            index=index,
            publication_id=_publication_id(link),
            title=self._fields["Title"],
            date=self._fields["Date"],
            link=link,
            description=self._fields.get("Description") or None,
            bill_number=self._fields.get("Bill_Number") or None,
        )


def parse_cbo_cost_estimates_feed(body: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> CboCostEstimatesFeed:
    """Read CBO's ``<response>`` of ``<item key="N">`` elements; every Link must name a publication."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_FEED_BYTES:
        raise CboSourceError("max_bytes must be a positive integer no greater than 64 MiB")
    scan = _FeedScan()
    scan_xml(
        body,
        start=scan.start,
        end=scan.end,
        data=scan.data,
        max_bytes=max_bytes,
        error_type=CboSourceError,
        label="CBO feed",
    )
    if len({item.publication_id for item in scan.items}) != len(scan.items):
        raise CboSourceError("CBO feed lists a publication more than once")
    return CboCostEstimatesFeed(tuple(scan.items))


def validate_cbo_estimate_document(capture: CapturedBodyResponse, *, max_bytes: int) -> None:
    """Prove the bytes are the PDF the locator named, by media type, magic and final URL.

    The capture already carries the URL, byte size and digest, so this returns
    nothing: it either raises or leaves the caller its exact bytes.
    """
    check_final_url(
        capture.resolved_url,
        capture.requested_url,
        error_type=CboSourceError,
        message="CBO estimate document final URL differs from its locator",
    )
    if len(capture.body) > max_bytes:
        raise CboSourceError("CBO estimate document exceeds its byte bound")
    check_pdf_bytes(capture.body, error_type=CboSourceError, label="CBO estimate document")


@dataclass(frozen=True, slots=True)
class CboBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float
    max_document_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_FEED_BYTES)
        check_byte_bound(self.max_document_bytes, "max_document_bytes", MAX_DOCUMENT_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class CboFeedAcquisition:
    feed: CboCostEstimatesFeed
    capture: CapturedBodyResponse
    request_count: int
    budget: CboBudget


@dataclass(frozen=True, slots=True)
class CboDocumentAcquisition:
    capture: CapturedBodyResponse
    request_count: int
    budget: CboBudget


@contextmanager
def _named_challenge(url: str) -> Iterator[None]:
    """Name cbo.gov's bot wall for what it is: no credential exists to be refused.

    The shared client maps 401/403 to ``CredentialRefusedError`` so a keyed
    family aborts rather than treating a refusal as a bad row. This family is
    keyless, so the same status means a bot wall, and the client retains the
    challenge body. The substitution keeps the acquisition context and refusal
    record the shared client attached, so the challenge bytes reach the caller.
    """
    try:
        yield
    except CredentialRefusedError as error:
        challenge = CboChallengeError(url)
        carried = ("cbo_acquisition", "refused_response")
        challenge.__dict__.update({key: error.__dict__[key] for key in carried if key in error.__dict__})
        raise challenge from error


class CboAcquirer(SourceAcquirer):
    """Keyless capture of the per-Congress feeds and, when a caller states one, an estimate PDF."""

    def __init__(
        self,
        *,
        budget: CboBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, CboBudget):
            raise TypeError("budget must be a CboBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-cbo-feed/1.0",
            label="CBO",
            error_type=CboSourceError,
            context_key="cbo_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> CboBudget:
        return self._budget

    def _acquire_feed(self, url: str, operation: str, max_bytes: int | None) -> CboFeedAcquisition:
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        with _named_challenge(url):
            feed, capture = self.capture_validated(
                url,
                media_types=FEED_MEDIA_TYPES,
                parse=lambda response, allowance: parse_cbo_cost_estimates_feed(response.body, max_bytes=allowance),
                max_bytes=limit,
                unavailable=CboUnavailableError,
                context={"operation": operation, "url": url},
            )
        return CboFeedAcquisition(feed, capture, self.request_count, self.budget)

    def acquire_per_congress_feed(self, congress: int, *, max_bytes: int | None = None) -> CboFeedAcquisition:
        """The one keyless route: one Congress's estimates to date, newest first."""
        return self._acquire_feed(cbo_per_congress_feed_locator(congress), "per-congress-feed", max_bytes)

    def acquire_cost_estimates_feed(self, *, max_bytes: int | None = None) -> CboFeedAcquisition:
        """Walled on every observation so far; kept so the refusal is recorded, not assumed."""
        return self._acquire_feed(cbo_cost_estimates_feed_locator(), "cost-estimates-feed", max_bytes)

    def acquire_estimate_document(self, url: str, *, max_bytes: int | None = None) -> CboDocumentAcquisition:
        """Capture one estimate PDF by a caller-stated cbo.gov locator.

        Every document path measured is walled, and a full browser-like header
        set does not pass it, so on the default transport this raises
        ``CboChallengeError``. Reaching a document needs a browser-backed
        ``transport`` injected into this acquirer; the locator, the bounds and
        the three identity proofs are here and ready for one.
        """
        locator = cbo_estimate_document_locator(url)
        limit = narrow_byte_limit(self.budget.max_document_bytes, max_bytes)
        with _named_challenge(locator):
            _, capture = self.capture_validated(
                locator,
                media_types=DOCUMENT_MEDIA_TYPES,
                parse=lambda response, allowance: validate_cbo_estimate_document(response, max_bytes=allowance),
                max_bytes=limit,
                unavailable=CboUnavailableError,
                context={"operation": "estimate-document", "url": locator},
            )
        return CboDocumentAcquisition(capture, self.request_count, self.budget)
