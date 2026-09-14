"""Supreme Court slip opinions: one term index, then the exact PDFs that index names.

``https://www.supremecourt.gov/opinions/slipopinion/{code}`` lists one term's
opinions with release number, decision date, docket number, case name, holding,
authoring Justice and reporter citation, and links each opinion's official PDF.
The site serves this keyless and, measured 2026-09-14, without demanding a
browser user agent: eleven requests, all ``200``.

Two routes, both bounded and both O(B) in the bytes captured: the term index
with its rows parsed, and one document the retained index stated. Nothing here
is written or published; the caller keeps ``capture.body``.

What the 2026-09-14 pins established, and why the checks below are shaped as
they are. The measurements are in
``corpora/supply-2026-09-02/receipts/port-P02-supreme-court-2026-09-14/``:

* **An index capture is one render at one instant.** The same URL answered two
  renders 2.5 minutes apart -- 66 links and nine unlinked rows, then 76 links --
  both ``cdn-cache: HIT`` with the same ``Last-Modified``. A later capture is
  not a check on an earlier one, and a link is only *what a retained index
  stated*. Links are kept byte-exact: two renders offered
  ``608us1r36d_febh.pdf`` and ``608us1r36d_21o3.pdf`` for one row, and both
  serve, with different lengths -- the trailing token is a revision, not a
  cache-buster. No URL here is ever derived from a docket number.
* **The publisher's term statement, not the caller's loop, names the term.** The
  salvaged SpicyRegs reader records (2026-08-22) a client that asked for OT2021
  and was served OT2023: sixty correctly parsed rows about to be stamped with
  the wrong term. That did not reproduce on 2026-09-14 and the checks stay: the
  page must state ``Term Year: {year}``, every slip link must sit under
  ``/opinions/{code}pdf/``, and every decision date must fall in the term's
  window. ``BoundedHttpCapture`` keeps one client per acquirer and does not
  clear cookies between operations, which is the condition that was seen.
* **Rows without an opinion link are rows.** Ten of 72 OT2025 rows stated no
  opinion link, one of them offering only a revision diff. Reading the first
  anchor in the name cell, as the salvaged reader does, makes that row's case
  name ``6/28/26``. Unlinked rows are kept with ``pdf_url`` absent.

Ported from the salvaged SpicyRegs reader with its term-code rule, link guard
and term assertion. Its page-*end* assignment is deliberately not ported: an
opinion's end page is inferred from the next opinion's start, which is
interpretation and belongs downstream of this repository's boundary. The
publisher-stated start page is kept.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from spicy_docs.sources.pdf_bytes import check_pdf_bytes
from spicy_docs.transport.captured import CapturedBodyResponse
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

SUPREME_COURT_SITE = "https://www.supremecourt.gov"
SLIP_OPINION_INDEX_PATH = "/opinions/slipopinion/"
HTML_MEDIA_TYPES = ("text/html",)
PDF_MEDIA_TYPES = ("application/pdf",)
#: Term indexes ran 103-113 KB across the four terms captured on 2026-09-14.
DEFAULT_MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
#: Slip PDFs ran 66-460 KB; a preliminary print holds a whole part of a volume.
DEFAULT_MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
#: The salvaged reader measured a 403 after ~80 requests in 25 minutes from one
#: address (2026-08-22) and settled on 2 s. Eleven requests 1.6 s apart on
#: 2026-09-14 were all served, which tests nothing about that threshold.
RECOMMENDED_MIN_REQUEST_INTERVAL_SECONDS = 2.0
MIN_TERM_YEAR, MAX_TERM_YEAR = 2000, 2099
#: The largest term captured held 72 rows; the bound is a runaway guard.
MAX_INDEX_ROWS = 2000
MAX_FIELD_LENGTH = 4096
SLIP_OPINION = "slip-opinion"
#: A pre-2021 index points into a bound volume or preliminary print instead of a
#: slip file; the salvaged reader measured 207 such rows over OT2017-OT2020.
#: OT2020 confirmed ``preliminaryprint``; no retained index states a bound volume.
VOLUME_PREFIXES = {"/opinions/preliminaryprint/": "preliminary-print", "/opinions/boundvolumes/": "bound-volume"}
_SITE_HOST = urlsplit(SUPREME_COURT_SITE).hostname
_TERM_LABEL_ID = "lblListTitle"
_REVISIONS_MARKER = "revisions"
_OPINION_ROW_CELLS = 6
#: The publisher spells a decision date ``9/04/26``; the term window proves the century.
_DECIDED = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{2})")
#: Every retained opinion PDF is linearized and its ``/L`` states the file length.
_LINEARIZED_LENGTH = re.compile(rb"/Linearized[^>]{0,64}?/L\s+([0-9]+)")
_LINEARIZATION_WINDOW = 2048


class SupremeCourtSourceError(ValueError):
    """The response cannot establish the requested Supreme Court term or document."""


class SupremeCourtUnavailableError(SupremeCourtSourceError):
    """Only this exact locator answered 404/410; it never means the term or opinion is absent."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Supreme Court source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def current_term_year(today: date | None = None) -> int:
    """The October Term in progress. A term opens in October and is named for that year.

    The default date is UTC's. Within hours of an October 1 boundary a caller
    that means a particular civil day should pass it.
    """
    value = today if today is not None else utc_now().date()
    if not isinstance(value, date):
        raise SupremeCourtSourceError("today must be a date")
    return value.year if value.month >= 10 else value.year - 1


def term_code(term_year: int) -> str:
    """The two-digit path segment for a term year.

    Confirmed from the publisher's own navigation on 2026-09-14: the OT2025
    index links ``href="24">2024``, ``href="23">2023`` and so on, and states
    ``Term Year: 2025`` for ``/25``.
    """
    if isinstance(term_year, bool) or not isinstance(term_year, int):
        raise SupremeCourtSourceError("term_year must be an integer")
    if not MIN_TERM_YEAR <= term_year <= MAX_TERM_YEAR:
        raise SupremeCourtSourceError(f"term_year must be from {MIN_TERM_YEAR} to {MAX_TERM_YEAR}")
    return str(term_year)[-2:]


def supreme_court_term_index_locator(term_year: int) -> str:
    return f"{SUPREME_COURT_SITE}{SLIP_OPINION_INDEX_PATH}{term_code(term_year)}"


@dataclass(frozen=True, slots=True)
class SupremeCourtRevision:
    """One ``Revisions:`` link: the publisher's date label and the document it names."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class SupremeCourtOpinion:
    """One index row in the publisher's spellings.

    ``release_number`` is the ``R-`` column and is not an integer -- OT2025 row
    ``D1`` is a decree. ``date_decided`` and ``citation`` are verbatim
    (``9/04/26``, ``609/2`` while preliminary, ``608 U.S. 85`` once final).
    ``pdf_url`` is absent when the row states no opinion link.
    """

    index: int
    release_number: str
    date_decided: str
    docket_number: str
    case_name: str
    holding: str | None
    author_code: str
    citation: str
    pdf_url: str | None
    pdf_kind: str | None
    page_start: str | None
    revisions: tuple[SupremeCourtRevision, ...]


@dataclass(frozen=True, slots=True)
class SupremeCourtTermIndex:
    """One render of one term index. ``stated_term`` is the page's own claim about which term it is."""

    term_year: int
    term_code: str
    index_url: str
    stated_term: str
    opinions: tuple[SupremeCourtOpinion, ...]

    @property
    def document_urls(self) -> frozenset[str]:
        """Every document this render named, opinions and revisions alike.

        Rebuilt per access in O(rows) over at most ``MAX_INDEX_ROWS``; a fetch
        loop pays it once per document, far below the request it guards.
        """
        return frozenset(
            [opinion.pdf_url for opinion in self.opinions if opinion.pdf_url]
            + [revision.url for opinion in self.opinions for revision in opinion.revisions]
        )


def _text(parts: list[str], label: str) -> str:
    value = " ".join("".join(parts).split())
    if len(value) > MAX_FIELD_LENGTH:
        raise SupremeCourtSourceError(f"Supreme Court index {label} exceeds its length bound")
    return value


def _classify_link(href: str, *, code: str) -> tuple[str, str, str | None]:
    """Recognise one index link, or refuse it by name.

    Returns ``(kind, document_url, page_start)``. A volume link's ``#page=N``
    says where in the volume the opinion begins and is not part of the resource,
    so it is reported separately and never fetched.
    """
    parts = urlsplit(urljoin(SUPREME_COURT_SITE, href))
    if (
        parts.scheme != "https"
        or parts.hostname != _SITE_HOST
        or parts.query
        or not parts.path.casefold().endswith(".pdf")
    ):
        raise SupremeCourtSourceError("Supreme Court index link is not an opinion PDF on the Court's own site")
    document_url = f"https://{parts.netloc}{parts.path}"
    if parts.path.startswith(f"/opinions/{code}pdf/"):
        if parts.fragment:
            raise SupremeCourtSourceError("Supreme Court slip opinion link carries an unexpected fragment")
        return SLIP_OPINION, document_url, None
    for prefix, kind in VOLUME_PREFIXES.items():
        if parts.path.startswith(prefix):
            page = parts.fragment.removeprefix("page=")
            if not parts.fragment.startswith("page=") or not page.isdecimal() or int(page) < 1:
                raise SupremeCourtSourceError("Supreme Court volume link states no page anchor")
            return kind, document_url, page
    raise SupremeCourtSourceError("Supreme Court index link is outside the requested term and the volume prints")


class _TermIndexHtml(HTMLParser):
    """Read the publisher's term label and every six-column opinion row, in one linear pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.term_label: list[str] = []
        self.rows: list[list[dict]] = []
        self._label_depth: int | None = None
        self._span_depth = 0
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._link: dict | None = None
        self._bold: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "span":
            self._span_depth += 1
            if self._label_depth is None and (values.get("id") or "").endswith(_TERM_LABEL_ID):
                self._label_depth = self._span_depth
        elif tag == "tr":
            # A row inside a row would be a nested table or an unclosed row, and
            # either would drop the outer row from the count without a word.
            if self._row is not None:
                raise SupremeCourtSourceError("Supreme Court index nests its rows")
            self._row, self._cell, self._link = [], None, None
        elif tag == "td" and self._row is not None:
            self._cell = {"parts": [], "links": [], "revised": False}
        elif tag == "b" and self._cell is not None:
            self._bold = []
        elif tag == "a" and self._cell is not None:
            href = values.get("href")
            if self._link is not None:
                raise SupremeCourtSourceError("Supreme Court index row nests its links")
            if not isinstance(href, str) or not href:
                raise SupremeCourtSourceError("Supreme Court index row states a link without a target")
            title = values.get("title")
            self._link = {"href": href, "title": title, "parts": [], "revision": self._cell["revised"]}
            self._cell["links"].append(self._link)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            if self._label_depth == self._span_depth:
                self._label_depth = None
            self._span_depth = max(self._span_depth - 1, 0)
        elif tag == "a":
            self._link = None
        elif tag == "b" and self._bold is not None:
            if self._cell is not None and "".join(self._bold).strip().casefold() == _REVISIONS_MARKER:
                self._cell["revised"] = True
            self._bold = None
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(self._cell)
            self._cell, self._bold = None, None
        elif tag == "tr" and self._row is not None:
            if len(self._row) == _OPINION_ROW_CELLS:
                if len(self.rows) >= MAX_INDEX_ROWS:
                    raise SupremeCourtSourceError("Supreme Court index lists more rows than supported")
                self.rows.append(self._row)
            self._row, self._cell, self._link = None, None, None

    def handle_data(self, data: str) -> None:
        if self._label_depth is not None:
            self.term_label.append(data)
        if self._bold is not None:
            self._bold.append(data)
        elif self._link is not None:
            self._link["parts"].append(data)
        elif self._cell is not None and not self._cell["revised"]:
            self._cell["parts"].append(data)


def _opinion(index: int, row: list[dict], *, code: str) -> SupremeCourtOpinion:
    """One row. The opinion link is the one stated before the ``Revisions:`` marker, if any."""
    release, decided, docket, name, author, citation = row
    opinions = [link for link in name["links"] if not link["revision"]]
    if len(opinions) > 1:
        raise SupremeCourtSourceError("Supreme Court index row states more than one opinion link")
    kind = page = url = holding = None
    if opinions:
        kind, url, page = _classify_link(opinions[0]["href"], code=code)
        holding = _text([opinions[0]["title"] or ""], "holding") or None
        case_name = _text(opinions[0]["parts"], "case name")
    else:
        case_name = _text(name["parts"], "case name")
    if not case_name:
        raise SupremeCourtSourceError("Supreme Court index row states no case name")
    return SupremeCourtOpinion(
        index=index,
        release_number=_text(release["parts"], "release number"),
        date_decided=_text(decided["parts"], "decision date"),
        docket_number=_text(docket["parts"], "docket number"),
        case_name=case_name,
        holding=holding,
        author_code=_text(author["parts"], "authoring Justice"),
        citation=_text(citation["parts"], "citation"),
        pdf_url=url,
        pdf_kind=kind,
        page_start=page,
        revisions=tuple(
            SupremeCourtRevision(_text(link["parts"], "revision label"), _classify_link(link["href"], code=code)[1])
            for link in name["links"]
            if link["revision"]
        ),
    )


def _assert_dates_are_in_the_term(index: SupremeCourtTermIndex) -> None:
    """The third of three independent statements that this page is the term requested.

    The publisher's label is checked before the rows are read and the term
    directory is checked per slip link; this checks the dates. A term's cases
    are decided between the September it opens and the end of the following
    calendar year -- loose enough never to fire on a real index, tight enough to
    catch a whole term's drift, which is the failure the salvaged reader was
    bitten by.
    """
    opens, closes = date(index.term_year, 9, 1), date(index.term_year + 1, 12, 31)
    for opinion in index.opinions:
        stated = _DECIDED.fullmatch(opinion.date_decided)
        try:
            if stated is None:
                raise ValueError("decision date is not M/D/YY")
            # Two-digit years on this route are 2000s; the term bound proves it.
            decided = date(2000 + int(stated[3]), int(stated[1]), int(stated[2]))
        except ValueError as error:
            raise SupremeCourtSourceError(
                f"Supreme Court index row {opinion.release_number} states an unreadable decision date"
            ) from error
        if not opens <= decided <= closes:
            raise SupremeCourtSourceError(
                f"Supreme Court index for {index.term_year} states a decision dated {opinion.date_decided} "
                f"({opinion.case_name}); the page served is not the term that was requested"
            )


def parse_supreme_court_term_index(
    body: bytes, *, term_year: int, max_bytes: int = DEFAULT_MAX_INDEX_BYTES
) -> SupremeCourtTermIndex:
    """Read one term index render. O(B) in the response bytes; one pass, no per-row rescan."""
    code = term_code(term_year)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_INDEX_BYTES:
        raise SupremeCourtSourceError("max_bytes must be a positive integer no greater than 16 MiB")
    if not isinstance(body, (bytes, bytearray)):
        raise SupremeCourtSourceError("body must be bytes")
    if not body:
        raise SupremeCourtSourceError("Supreme Court index response is empty; a nonempty page was requested")
    if len(body) > max_bytes:
        raise SupremeCourtSourceError("Supreme Court index exceeds its byte bound")
    try:
        text = bytes(body).decode("utf-8")
    except UnicodeDecodeError as error:
        raise SupremeCourtSourceError("Supreme Court index is not the UTF-8 the publisher declares") from error
    parser = _TermIndexHtml()
    try:
        parser.feed(text)
        parser.close()
    except SupremeCourtSourceError:
        raise
    except Exception as error:  # pragma: no cover - HTMLParser is lenient by design
        raise SupremeCourtSourceError("Supreme Court index HTML could not be parsed") from error
    if not parser.rows:
        raise SupremeCourtSourceError("Supreme Court index states no opinion rows")
    # The publisher's own label first: when a whole different term is served, it
    # names that failure directly instead of leaving it to the first odd link.
    stated_term = _text(parser.term_label, "term label")
    if stated_term != f"Term Year: {term_year}":
        raise SupremeCourtSourceError(f"Supreme Court index states {stated_term!r}, not the requested term {term_year}")
    index = SupremeCourtTermIndex(
        term_year=term_year,
        term_code=code,
        index_url=supreme_court_term_index_locator(term_year),
        stated_term=stated_term,
        opinions=tuple(_opinion(number, row, code=code) for number, row in enumerate(parser.rows)),
    )
    _assert_dates_are_in_the_term(index)
    return index


@dataclass(frozen=True, slots=True)
class SupremeCourtDocument:
    """What the captured bytes themselves state about the document the index named."""

    url: str
    pdf_version: str
    byte_size: int
    linearized_length: int | None


def read_supreme_court_pdf(
    body: bytes, *, url: str, final_url: str, max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES
) -> SupremeCourtDocument:
    """Prove the bytes are one complete PDF served by the link the index stated.

    An opinion PDF names no docket a reader can check, so identity is the
    request: a URL a retained index stated, a final URL equal to it, the
    publisher's ``application/pdf``, and the ``%PDF-`` magic. Completeness has
    two statements: every retained opinion ends ``%%EOF``, and every one is
    linearized with a ``/L`` equal to its own length. Both numbers come from the
    file being checked, so they catch truncation, not substitution, and a
    non-linearized PDF states no ``/L`` and is not refused for it.

    ``transport.download.validate_body_prefix`` is not called: it belongs to the
    streamed download path and only rejects HTML, which the magic check
    subsumes. ``congress/crs_files.py`` reads its PDFs the same way.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_DOCUMENT_BYTES:
        raise SupremeCourtSourceError("max_bytes must be a positive integer no greater than 64 MiB")
    check_final_url(
        final_url,
        url,
        error_type=SupremeCourtSourceError,
        message="Supreme Court document final URL differs from the link the index stated",
    )
    if not isinstance(body, (bytes, bytearray)):
        raise SupremeCourtSourceError("body must be bytes")
    body = bytes(body)
    if len(body) > max_bytes:
        raise SupremeCourtSourceError("Supreme Court document exceeds its byte bound")
    version = check_pdf_bytes(body, error_type=SupremeCourtSourceError, label="Supreme Court document")
    stated = _LINEARIZED_LENGTH.search(body, 0, _LINEARIZATION_WINDOW)
    length = int(stated[1]) if stated else None
    if length is not None and length != len(body):
        raise SupremeCourtSourceError("Supreme Court document length differs from the length it states")
    return SupremeCourtDocument(url, version, len(body), length)


@dataclass(frozen=True, slots=True)
class SupremeCourtBudget:
    max_requests: int
    max_index_bytes: int
    max_document_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_index_bytes, "max_index_bytes", MAX_INDEX_BYTES)
        check_byte_bound(self.max_document_bytes, "max_document_bytes", MAX_DOCUMENT_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class SupremeCourtIndexAcquisition:
    index: SupremeCourtTermIndex
    capture: CapturedBodyResponse
    request_count: int
    budget: SupremeCourtBudget


@dataclass(frozen=True, slots=True)
class SupremeCourtDocumentAcquisition:
    document: SupremeCourtDocument
    capture: CapturedBodyResponse
    request_count: int
    budget: SupremeCourtBudget


class SupremeCourtAcquirer(SourceAcquirer):
    """Keyless capture of one term index and the documents that render named."""

    def __init__(
        self,
        *,
        budget: SupremeCourtBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, SupremeCourtBudget):
            raise TypeError("budget must be a SupremeCourtBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-supreme-court/1.0",
            label="Supreme Court",
            error_type=SupremeCourtSourceError,
            context_key="supreme_court_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> SupremeCourtBudget:
        return self._budget

    def acquire_term_index(self, term_year: int, *, max_bytes: int | None = None) -> SupremeCourtIndexAcquisition:
        """One GET for one term. The result describes that render and no other."""
        locator = supreme_court_term_index_locator(term_year)
        effective = replace(self.budget, max_index_bytes=narrow_byte_limit(self.budget.max_index_bytes, max_bytes))
        index, capture = self.capture_validated(
            locator,
            media_types=HTML_MEDIA_TYPES,
            parse=lambda response, limit: parse_supreme_court_term_index(
                response.body, term_year=term_year, max_bytes=limit
            ),
            max_bytes=effective.max_index_bytes,
            unavailable=SupremeCourtUnavailableError,
            context={
                "operation": "term-index",
                "termYear": term_year,
                "url": locator,
                "budget": asdict(effective),
            },
        )
        return SupremeCourtIndexAcquisition(index, capture, self.request_count, effective)

    def acquire_document(
        self, index: SupremeCourtTermIndex, url: str, *, max_bytes: int | None = None
    ) -> SupremeCourtDocumentAcquisition:
        """One GET for one document a retained index stated. The index is the identity."""
        if not isinstance(index, SupremeCourtTermIndex):
            raise TypeError("index must be a SupremeCourtTermIndex")
        if url not in index.document_urls:
            raise SupremeCourtSourceError("the retained Supreme Court index does not state that document URL")
        effective = replace(
            self.budget, max_document_bytes=narrow_byte_limit(self.budget.max_document_bytes, max_bytes)
        )
        document, capture = self.capture_validated(
            url,
            media_types=PDF_MEDIA_TYPES,
            parse=lambda response, limit: read_supreme_court_pdf(
                response.body, url=url, final_url=response.resolved_url, max_bytes=limit
            ),
            max_bytes=effective.max_document_bytes,
            unavailable=SupremeCourtUnavailableError,
            context={
                "operation": "opinion-document",
                "termYear": index.term_year,
                "indexUrl": index.index_url,
                "url": url,
                "budget": asdict(effective),
            },
        )
        return SupremeCourtDocumentAcquisition(document, capture, self.request_count, effective)
