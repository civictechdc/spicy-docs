"""CBO cost estimates: the per-Congress XML feeds, and what the bot wall refuses.

The feed CBO advertises, ``www.cbo.gov/cost-estimates/xml``, is behind a
DataDome bot wall and has never answered a raw-byte request: ``403`` with
``x-datadome: protected`` to plain and browser-like clients alike, and the
cookie the wall sets changes nothing. The wall is path-scoped over
``/publication/<id>`` and every PDF path, so the estimate **document** has no
keyless route either. ``403`` here is named a challenge, not a credential
refusal: this family holds no credential.

**No header set reaches the documents; only a browser-backed transport could.**
Re-probed 2026-09-14 (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-14/q3-cbo-bot-wall``)
with a complete browser-like header set, the estimate PDF, the advertised XML
feed and the publication page each answered the identical ``403`` while the
per-Congress feed answered ``200`` to that same client -- so the headers are not
what is refused, and the refusal body is a JavaScript challenge no header can
pass. ``acquire_estimate_document`` therefore needs a browser-backed
``transport`` injected by the caller (see ``sources/zyte.py``); this module does
not and will not try to solve the challenge.

One tier answers keyless: ``www.cbo.gov/rss/{congress}congress-cost-estimates.xml``,
one file per Congress, in CBO's own XML -- **not RSS 2.0** -- a ``<response>``
root of ``<item key="N">`` elements carrying exactly ``Title``, ``Date``,
``Link``, ``Description`` and ``Bill_Number``, with no channel header and no
namespace. Topic labels, budget-function codes, UMRA mandate flags and the PAYGO
flag are **not** in these bytes; they appear only in RefSpec's acknowledged
reconstruction of the walled feed, never in a verified capture. An unknown child
element refuses the whole feed, so the day
CBO publishes one it is visible instead of silently dropped. A per-Congress feed
is that Congress to date, newest first, and an observation, never a catalog; a
Congress with no file answers 404 with a Drupal HTML page, which is
requested-empty, not absence.

The feed is also a row route, read for every Congress: the only one for the
112th-113th, whose BILLSTATUS states no estimate, and elsewhere the estimates
no BILLSTATUS record lists. ``cbo_feed_bills`` maps each item to the bill its
``Bill_Number`` (or, where that is empty, its title) names, and
``interpretation.bill_family.build_cbo_feed_cost_estimates`` shapes the rows,
``source`` ``cbo_feed``, which a host merges with BILLSTATUS's. Congress.gov's
bill record lists the same items, regrouped by the same ``Bill_Number``, so it
is not a second route.

Byte counts, digests and the measurements behind every claim:
``docs/sources/cbo.md`` and the receipts named above.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.reading.xml import scan_xml
from spicy_docs.schemas.cost_estimate_tables import (
    FOUND_BY_BILL_NUMBER,
    FOUND_BY_BILL_NUMBER_TITLE,
    FOUND_BY_TITLE,
    FOUND_BY_TITLE_LAW,
)
from spicy_docs.schemas.law_tables import law_id
from spicy_docs.sources.congress.bill_status import BILL_TYPES, BillIdentity
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    named_challenge,
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


class CboFeedBillError(CboSourceError):
    """A feed item names a bill no rule maps: ``field`` is ``bill_number``, ``title`` or ``law_bills``, ``shape`` how.

    A ``Bill_Number``'s shape is its spelling with every digit run as ``N``, or
    ``title-disagrees`` for a bare number whose title leads with another
    number; a title's is ``two-citations``, ``not-at-start`` or
    ``unknown-form``; the host's law map's is ``not-a-bill-id`` or
    ``other-congress``.  None copies more than that of the publisher's text.
    """

    def __init__(self, field: str, shape: str) -> None:
        self.field, self.shape = field, shape
        super().__init__(f"CBO feed {field} {shape!r} names no bill this rule maps")


#: How CBO spells each measure type in ``Bill_Number``, as its abbreviation
#: words.  Every form in the 112th, 113th and 116th-119th feeds (2026-09-14 and
#: -28) is those words, each ended by a period, a space or both, then the
#: number: ``H.R. 8``, ``H. J. Res. 48``, ``H.J.Res. 124``, ``H.Con.Res 14``,
#: ``H.R.681``, ``S.  1591``, ``H.r. 4679``.  One item never names several
#: bills in any of them.  An amendment (``S.A. 948``), trailing text
#: (``H.R. 7529,``) and a list refuse: guessing a type or splitting a list is a
#: rule no measured form needed.  So does a bare number (``700``) here; a whole
#: feed reads one through its title where they agree (:func:`bare_number_bill`).
_BILL_TYPE_WORDS: dict[tuple[str, ...], str] = {
    ("h", "r"): "hr",
    ("s",): "s",
    ("h", "j", "res"): "hjres",
    ("s", "j", "res"): "sjres",
    ("h", "con", "res"): "hconres",
    ("s", "con", "res"): "sconres",
    ("h", "res"): "hres",
    ("s", "res"): "sres",
}
_SEPARATOR = r"(?:\.\s*|\s+)"
_BILL_NUMBER = re.compile(rf"(?P<words>(?:[A-Za-z]+{_SEPARATOR})+)(?P<number>[1-9][0-9]*)")


def _capitalized(word: str) -> str:
    """``res`` as ``R[eE][sS]``: a title capitalizes an abbreviation, which is what keeps prose from reading as one."""
    return word[0].upper() + "".join(f"[{letter}{letter.upper()}]" for letter in word[1:])


#: The same grammar, found anywhere in a title: capitalized, so prose cannot
#: read as one (``Obama's 2013`` is not ``S. 2013``), starting a token (not
#: after a letter, digit or period, so ``U.S. 1`` is not ``S. 1``), and
#: ending at the number (``S. 2nd Session`` is not ``S. 2``, and refuses).
_TITLE_CITATION = re.compile(
    r"(?<![A-Za-z0-9.])(?:"
    + "|".join(_SEPARATOR.join(map(_capitalized, words)) for words in _BILL_TYPE_WORDS)
    + rf"){_SEPARATOR}[1-9][0-9]*(?![0-9A-Za-z])"
)
#: A title leading with an abbreviation and a number that is no bill type
#: (``S.A. 948``, ``H. Amdt. 5``): short words, at least one period, then a
#: digit.  ``Public Law 112-8`` and ``Act of 2012`` are prose, not this.
_ABBREVIATED_LEAD = re.compile(r"(?=[^0-9]*\.)(?:[A-Za-z]{1,5}(?:\.\s*|\s+)){1,4}[0-9]")


def feed_item_bills(congress: int, bill_number: str | None) -> tuple[BillIdentity, ...]:
    """The bills one feed item's ``Bill_Number`` names in its feed's Congress; ``()`` when the publisher left it empty.

    An empty ``Bill_Number`` is CBO's own value (a suspension-calendar notice,
    a reconciliation title), so it names no bill rather than refusing; a
    nonempty one outside the measured forms raises :class:`CboFeedBillError`.
    """
    if bill_number is None:
        return ()
    match = _BILL_NUMBER.fullmatch(bill_number.strip())
    words = None if match is None else tuple(word.casefold() for word in re.findall(r"[A-Za-z]+", match["words"]))
    bill_type = None if words is None else _BILL_TYPE_WORDS.get(words)
    if match is None or bill_type is None:
        raise CboFeedBillError("bill_number", re.sub(r"[0-9]+", "N", bill_number))
    return (BillIdentity(congress, bill_type, int(match["number"])),)


@dataclass(frozen=True, slots=True)
class PublicLawCitation:
    """A public law a title leads with (``P.L. 111-322``): its own Congress and number, which need not be the feed's."""

    congress: int
    number: int


#: A public-law citation as the feed titles spell one, capitalized and starting a token: ``P.L. 112-6`` and
#: ``Public Law 112-8`` lead nine titles of the 108th-119th feeds, and ``Public Law106-348`` occurs later in one.
#: The law's own Congress is stated, so a law of another Congress (the 112th feed's P.L. 111-322) reads as that.
_PUBLIC_LAW = re.compile(
    r"(?<![A-Za-z0-9.])(?:P\.\s?L\.|Public\s+Law)\s*(?P<congress>[1-9][0-9]*)-(?P<number>[1-9][0-9]*)(?![0-9A-Za-z])"
)


def title_citation(congress: int, title: str) -> BillIdentity | PublicLawCitation | None:
    """The bill, or public law, a title names by leading with its citation; ``None`` where it leads with neither.

    A bill citation reads in the feed's Congress (``H.R. 4402, Critical
    Minerals Policy Act of 2012``); a public law in its own (``P.L.
    111-322, the Continuing Appropriations ...``).  Prose names nothing
    (``Sequester Replacement Reconciliation Act``).  Anything ambiguous
    refuses: a second citation of another bill after a leading bill, or of
    another law after a leading law (``two-citations``); a bill citation after
    the start (``not-at-start``: the 119th's ``... in Title IV of H.R. 1``);
    an abbreviation and number that is no bill type or law (``unknown-form``).
    What a title cites after its lead in the other kind is its subject, not a
    second name for it: a law a bill amends (``H.R. 4596, A bill to amend
    Public Law 97-435 ...``), a resolution a law follows (``Public Law 119-21,
    to Provide for Reconciliation Pursuant to Title II of H. Con. Res. 14``).
    """
    laws = list(_PUBLIC_LAW.finditer(title))
    citations = list(_TITLE_CITATION.finditer(title))
    if laws and laws[0].start() == 0:
        if len({(law["congress"], law["number"]) for law in laws}) != 1:
            raise CboFeedBillError("title", "two-citations")
        return PublicLawCitation(int(laws[0]["congress"]), int(laws[0]["number"]))
    if not citations:
        if _ABBREVIATED_LEAD.match(title):
            raise CboFeedBillError("title", "unknown-form")
        return None
    if citations[0].start() != 0:
        raise CboFeedBillError("title", "not-at-start")
    bills = {bill for citation in citations for bill in feed_item_bills(congress, citation.group(0))}
    if len(bills) != 1:
        raise CboFeedBillError("title", "two-citations")
    return bills.pop()


#: A ``Bill_Number`` that states a number and no type: the 117th's ``700`` and the 118th's ``106``, 2026-09-28.
_BARE_NUMBER = re.compile(r"[1-9][0-9]*")


def bare_number_bill(congress: int, bill_number: str, title: str) -> BillIdentity:
    """The bill a bare-number ``Bill_Number`` names, its type read from the citation the title leads with.

    Owner decision 2026-09-28: the 117th's ``700`` titled ``H.R. 700, an act to
    designate ...`` is H.R. 700, and the 118th's ``106`` titled ``S. 106,
    Commitment to Veteran Support and Outreach Act`` is S. 106.  Both
    statements must agree: a title leading with another number refuses as
    ``title-disagrees``, and one leading with no single bill (prose, a law, an
    ambiguous citation) leaves the number without a type and refuses as the
    bare number did, ``N``.
    """
    try:
        cited = title_citation(congress, title)
    except CboFeedBillError:
        cited = None
    if not isinstance(cited, BillIdentity):
        raise CboFeedBillError("bill_number", "N")
    if cited.number != int(bill_number):
        raise CboFeedBillError("bill_number", "title-disagrees")
    return cited


#: A host's map from a public law's ``laws.law_id`` (``111-public-322``) to the ``bill_id`` that enacted it
#: (``111-hr-3082``), read from its ``laws`` table; spicy-docs reads no table itself.
LawBills = Mapping[str, str]
_BILL_ID = re.compile(r"(?P<congress>[1-9][0-9]*)-(?P<type>[a-z]+)-(?P<number>[1-9][0-9]*)")


def law_bill(law_bills: LawBills, law: PublicLawCitation) -> BillIdentity | None:
    """The bill the host's laws table says enacted ``law``, or ``None`` where the map has no entry.

    A value that is no ``bill_id`` (``hr-1363``, or ``112-house-1363``, whose
    type is none) refuses as ``not-a-bill-id``, and a bill of another Congress
    than the law's (``112-hr-3082`` for P.L. 111-322) as ``other-congress``: a
    law is enacted from a bill of its own Congress.  Either is
    :class:`CboFeedBillError`, field ``law_bills``: the host's map is wrong, and
    no bill is guessed from it.
    """
    stated = law_bills.get(law_id(law.congress, "public", law.number))
    if stated is None:
        return None
    match = _BILL_ID.fullmatch(stated) if isinstance(stated, str) else None
    if match is None or match["type"] not in BILL_TYPES:
        raise CboFeedBillError("law_bills", "not-a-bill-id")
    if int(match["congress"]) != law.congress:
        raise CboFeedBillError("law_bills", "other-congress")
    return BillIdentity(law.congress, match["type"], int(match["number"]))


@dataclass(frozen=True, slots=True)
class CboFeedBill:
    """One bill a feed names, the publication ids of the items naming it in feed order, and how each named it.

    ``found_by`` is each item's way, in the same order: ``bill_number``,
    ``bill_number_title``, ``title`` or ``title_law``
    (``schemas.cost_estimate_tables.FOUND_BY``), which the bill's row for that
    item publishes.
    """

    identity: BillIdentity
    publication_ids: tuple[str, ...]
    found_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CboFeedBills:
    """The bill set a feed names, sorted by type and number, and every item that named none.

    ``unnamed`` counts the items whose ``Bill_Number`` is empty and whose title
    leads with no citation, and ``public_law`` those whose title leads with a
    public law the host's map did not name a bill for (every one, without a
    map); ``refused`` holds
    ``(publication_id, field, shape)`` for every item
    :class:`CboFeedBillError` refused.  Sorted, because a feed's order within
    one ``Date`` differs between captures whose items are identical.
    """

    congress: int
    bills: tuple[CboFeedBill, ...]
    unnamed: int
    refused: tuple[tuple[str, str, str], ...]
    public_law: int = 0


def cbo_feed_bills(feed: CboCostEstimatesFeed, congress: int, *, law_bills: LawBills | None = None) -> CboFeedBills:
    """Map every item of one Congress's feed to its bills, in one pass; refusals are counted, never dropped.

    An item's ``Bill_Number`` is read when it states one and its title only
    when it does not, so a title never overrides the publisher's own number;
    a bare number, which states no type, reads through the title's leading
    citation of that same number (``bill_number_title``, :func:`bare_number_bill`).
    A blank item whose title leads with a public law names the bill
    ``law_bills``, the host's laws table, says enacted it (``title_law``: the
    110th's P.L. 110-50, the 112th's P.L. 112-8); without the map, or where it
    has no entry, it is counted as ``public_law`` and names none.
    """
    named: dict[BillIdentity, list[tuple[str, str]]] = {}
    unnamed = public_law = 0
    refused: list[tuple[str, str, str]] = []
    for item in feed.items:
        way = FOUND_BY_BILL_NUMBER
        try:
            if item.bill_number is not None and _BARE_NUMBER.fullmatch(item.bill_number):
                bills, way = (bare_number_bill(congress, item.bill_number, item.title),), FOUND_BY_BILL_NUMBER_TITLE
            elif item.bill_number is not None:
                bills = feed_item_bills(congress, item.bill_number)
            else:
                cited = title_citation(congress, item.title)
                way = FOUND_BY_TITLE
                if isinstance(cited, PublicLawCitation):
                    enacted = None if law_bills is None else law_bill(law_bills, cited)
                    if enacted is None:
                        bills = ()
                        public_law += 1
                    else:
                        bills, way = (enacted,), FOUND_BY_TITLE_LAW
                elif cited is None:
                    bills = ()
                    unnamed += 1
                else:
                    bills = (cited,)
        except CboFeedBillError as error:
            refused.append((item.publication_id, error.field, error.shape))
            continue
        for bill in bills:
            named.setdefault(bill, []).append((item.publication_id, way))
    ordered = sorted(named, key=lambda bill: (bill.bill_type, bill.number))
    return CboFeedBills(
        congress,
        tuple(
            CboFeedBill(bill, tuple(p for p, _ in named[bill]), tuple(w for _, w in named[bill])) for bill in ordered
        ),
        unnamed,
        tuple(refused),
        public_law,
    )


def feed_item_pub_date(item: CboEstimateItem) -> str:
    """The item's ``Date`` as the UTC instant BILLSTATUS spells a ``pubDate`` in (``2013-06-20T02:27:22Z``).

    The feed states RFC 2822 local time (``Wed, 19 Jun 2013 22:27:22 -0400``);
    Congress.gov lists the same instant in this spelling for all 43 feed items
    sampled on 2026-09-28, and a version column has to sort as text.  A date
    without an offset refuses: it names no instant.
    """
    try:
        moment = parsedate_to_datetime(item.date)
    except (TypeError, ValueError) as error:
        raise CboSourceError("CBO feed item Date is not an RFC 2822 date") from error
    if moment.tzinfo is None:
        raise CboSourceError("CBO feed item Date states no UTC offset")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _named_challenge(url: str) -> AbstractContextManager[None]:
    """cbo.gov's bot wall, named for what it is: no credential exists to be refused.

    Delegates to the shared ``named_challenge`` (``transport/source_acquirer.py``),
    which every keyless family uses so a 401/403 arrives as that family's own
    error -- catchable alongside its other errors -- rather than escaping as
    ``CredentialRefusedError``.
    """
    return named_challenge(url, error_type=CboChallengeError, context_key="cbo_acquisition")


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
