"""Bounded traversal of a publisher's paged JSON list operation with exact page evidence.

A ``JsonPageFamily`` states each publisher's contract as data: host, method, how
the next page is named, where the count lives and how the credential is spelled in
its header; credentials travel only as a request header, never in a URL or a
request body, and a page that echoes the credential is refused without retaining
its bytes. Callers own selection, retention and recovery. The reader refuses to
end a traversal silently: a repeated or foreign continuation, a changed declared
count, an observed total disagreeing with the declared one, or a page bound
reached before the publisher's terminal page are refusals, not quiet ends, and a
declared count of zero is an observation of that query on that day, not source
absence.

``records_key`` is a top-level key for most routes; a tuple path reaches rows a
publisher nests inside a wrapper object. A detail route's single-object shape
needs the explicit ``single_record`` opt-in on ``page()``/``pages()`` -- off by
default so a wrong or mismatched ``records_key`` resolving to a wrapper object
still refuses instead of reading as one bogus record, and an empty object refuses
either way because empty success is not absence.

**A walk that agrees with its count can still be wrong.** A list that shifts
while it is read (Congress.gov sorted by ``updateDate``, CRS, FCC ECFS) can
repeat one record and skip another while serving exactly the declared total:
the 119th Congress amendments walk served its declared 7,066 rows but 7,013
distinct amendments (spicy-regs ``build_amendments``, 2026-09-23). A terminal
disagreement raises ``DeclaredCountMismatch`` and a total that moves mid-walk
``DeclaredCountChanged``, each carrying both numbers; agreement proves only the
row count. ``pool_walks`` repeats whole walks of one query, keyed by a caller's
identity, and settles on the first of two things:

- **A clean walk stands alone.** A walk with no repeated identity whose
  distinct count equals its declared total is the list: a skip needs a repeat
  unless the population changes mid-walk, and a changed total is refused.
- **Otherwise the walks since the declared total last changed are pooled**,
  keeping each identity's newest version, until the pool holds exactly the
  declared total. A changed total starts a new pool, so a record deleted
  without replacement cannot fill a skipped record's slot, and a walk whose
  total changes mid-walk is spent and pooling restarts after it.

**Known limit:** a deletion offset by an insertion leaves the total unchanged,
so the pool keeps the deleted record. If every walk in the pool skipped one
live record -- the inserted one or any other -- the deleted record fills its
slot and the pool settles wrong; no comparison of identity sets against a
count can see that, and a test pins it. When no live record is skipped by
every walk the pool overfills instead and the query refuses. A query still
unsettled after ``max_passes`` raises ``IncompleteWalkError``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    utc_now,
)

from .json_input import load_decimal_json

if TYPE_CHECKING:
    import httpx

MAX_PAGE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_PAGE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_PAGES = 100
# Whole walks a pooled enumeration may spend on one query; spicy-regs' CRS and ECFS hosts used three.
DEFAULT_POOL_PASSES = 3
# Query parameter names publishers accept credentials under; they must never appear in a retained URL.
CREDENTIAL_QUERY_NAMES = frozenset({"api_key", "apikey", "api-key", "key", "token", "access_token"})
type NextKind = Literal["url", "page-number", "offset"]


class PagedJsonSourceError(ValueError):
    """The request or a page cannot establish the selected list traversal."""


class PagedJsonUnavailableError(PagedJsonSourceError):
    """Only the exact requested page URL answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"list source answered HTTP {capture.status_code} for the requested page")
        self.capture = capture


class DeclaredCountMismatch(PagedJsonSourceError):
    """A walk reached the publisher's terminal page having served a total other than the one it declared.

    Raised only at the terminal page, so ``observed`` is everything the walk
    served; a host that tolerates a bounded over-declaration reads the two
    numbers here instead of the message.
    """

    def __init__(self, message: str, *, declared: int, observed: int) -> None:
        super().__init__(message)
        self.declared = declared
        self.observed = observed


class DeclaredCountChanged(PagedJsonSourceError):
    """The publisher's declared total moved between two pages of one walk: the population changed under it."""

    def __init__(self, message: str, *, declared: int, changed_to: int) -> None:
        super().__init__(message)
        self.declared = declared
        self.changed_to = changed_to


class IncompleteWalkError(PagedJsonSourceError):
    """Pooled walks ran out of passes before a clean walk or a pool matching the declared total.

    ``declared`` is the latest total the publisher stated; ``distinct`` the
    identities pooled since it last changed; ``restarted`` the passes spent on a
    total that changed mid-walk.
    """

    def __init__(self, label: str, *, declared: int, distinct: int, passes: int, restarted: int) -> None:
        message = f"{label}: pooled {distinct:,} of {declared:,} declared records after {passes} passes"
        if restarted:
            message += f"; {restarted} of them saw the declared count change mid-walk"
        super().__init__(message)
        self.declared = declared
        self.distinct = distinct
        self.passes = passes
        self.restarted = restarted


def normalize_url(url: str, *, drop: frozenset[str] = frozenset()) -> str:
    """Spell a publisher URL the way the client will send it, so request and final URL agree.

    Congress.gov continuations carry an unencoded space (``sort=updateDate desc``);
    re-encoding the query makes the requested and resolved URLs identical. SAM
    continuations carry an ``api_key=REPLACE_WITH_API_KEY`` placeholder, which
    ``drop`` removes because the credential travels as a header. The publisher's
    raw spelling stays in the retained page bytes.
    """
    parts = urlsplit(url)
    pairs = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name not in drop]
    return urlunsplit(
        (parts.scheme, parts.netloc, quote(parts.path, safe="/%:@!$&'()+,;="), urlencode(pairs, safe="*"), "")
    )


def query_value(url: str, name: str) -> str | None:
    """One query parameter's value, ``None`` if absent; a repeated parameter is refused."""
    values = [value for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True) if key == name]
    if len(values) > 1:
        raise PagedJsonSourceError(f"list URL repeats its {name} parameter")
    return values[0] if values else None


def with_query(url: str, name: str, value: str) -> str:
    """Replace one query parameter, dropping any existing copies, and drop the fragment."""
    parts = urlsplit(url)
    pairs = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key != name]
    pairs.append((name, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs, safe="*"), ""))


@dataclass(frozen=True, slots=True)
class JsonPageFamily:
    """A publisher's list-page contract, stated as data rather than code.

    ``next_kind`` ``url`` reads a full next-page URL at ``next_path``;
    ``page-number`` reads it as the next page number or a has-next flag (``true``
    means one past the page requested) and rewrites ``page_field`` in the query
    (GET) or JSON body (POST); ``offset`` has no publisher continuation and
    advances ``offset_field`` by the rows received until a short page.
    ``count_kind`` ``exact`` checks the declared count against the walk;
    ``advisory`` records a count that may drift or exceed what its pages reach, so
    only the continuation ends the walk.
    """

    name: str
    label: str
    host: str
    next_path: tuple[str, ...] | None = None
    count_path: tuple[str, ...] | None = None
    credential_header: str | None = "X-Api-Key"
    credential_format: str = "{key}"
    requires_credential: bool = True
    method: Literal["GET", "POST"] = "GET"
    next_kind: NextKind = "url"
    page_field: str = "page"
    offset_field: str = "offset"
    limit_field: str = "limit"
    drop_query_names: frozenset[str] = frozenset()
    count_kind: Literal["exact", "advisory"] = "exact"
    media_types: tuple[str, ...] = ("application/json",)
    # Publisher-stated reach bounds, so every walk refuses in one request rather
    # than paying its way to the publisher's error: SAM serves at most 10,000
    # records per query shape; regulations.gov serves at most page[number] 40.
    max_reachable_records: int | None = None
    max_page_number: int | None = None
    window_hint: str = "query window"

    def __post_init__(self) -> None:
        for field_name in ("name", "label", "host"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be a nonempty trimmed string")
        if self.next_kind in ("url", "page-number") and not self.next_path:
            raise ValueError(f"next_kind {self.next_kind!r} requires next_path")
        if self.next_kind == "offset" and self.next_path:
            raise ValueError("an offset walk has no publisher continuation; leave next_path unset")
        if self.next_kind == "url" and self.method == "POST":
            raise ValueError("a POST list cannot follow a next URL; use page-number")
        if self.requires_credential and not self.credential_header:
            raise ValueError("a family that requires a credential must name its header")
        if "{key}" not in self.credential_format:
            raise ValueError("credential_format must contain {key}")
        if not self.media_types or not all(isinstance(value, str) and value for value in self.media_types):
            raise ValueError("media_types must name at least one media type")
        for name in ("max_reachable_records", "max_page_number"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")

    def check_url(self, url: str) -> str:
        """Only this publisher's HTTPS host, spelled as it will be sent, and never a credential in the query."""
        parts = urlsplit(url) if isinstance(url, str) else None
        if parts is None or parts.scheme != "https" or parts.hostname != self.host or not parts.path:
            raise PagedJsonSourceError(f"{self.label} list URL must be an HTTPS {self.host} route")
        normalized = normalize_url(url, drop=self.drop_query_names)
        names = {name.casefold() for name, _ in parse_qsl(urlsplit(normalized).query, keep_blank_values=True)}
        if names & CREDENTIAL_QUERY_NAMES:
            raise PagedJsonSourceError(f"{self.label} list URL must not carry a credential")
        return normalized


def _lookup(value: Mapping[str, Any], path: tuple[str, ...]) -> object:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _key_label(records_key: str | tuple[str, ...]) -> str:
    """Spell a records key the way a reader would ask for it, not as a Python repr."""
    return records_key if isinstance(records_key, str) else ".".join(records_key)


def _encode_body(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class JsonPage:
    """One exact list response, its rows as the publisher spelled them, and the next request if any.

    ``records_key`` is a top-level key for most publishers; a tuple reaches rows a
    publisher nests inside a wrapper object. A detail route answering one record as
    an object rather than an array at ``records_key`` reads as a single-record page
    when the caller opted in with ``page()``/``pages()``'s ``single_record``.
    """

    page_index: int
    records_key: str | tuple[str, ...]
    capture: CapturedBodyResponse
    records: tuple[Mapping[str, Any], ...]
    declared_count: int | None
    next_url: str | None
    request_body: Mapping[str, Any] | None = None
    next_body: Mapping[str, Any] | None = None

    @property
    def sha256(self) -> str:
        return self.capture.sha256


@dataclass(frozen=True, slots=True)
class PagedJsonBudget:
    """Bounds for each page request; pacing persists across the client's pages."""

    max_requests: int
    max_page_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_page_bytes, "max_page_bytes", MAX_PAGE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


class PagedJsonReader(SourceAcquirer):
    """Walk one publisher's list pages; each page is one bounded operation with evidence."""

    def __init__(
        self,
        *,
        family: JsonPageFamily,
        budget: PagedJsonBudget,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(family, JsonPageFamily):
            raise TypeError("family must be a JsonPageFamily")
        if not isinstance(budget, PagedJsonBudget):
            raise TypeError("budget must be a PagedJsonBudget")
        if api_key is not None and (not isinstance(api_key, str) or not api_key.strip() or api_key != api_key.strip()):
            raise ValueError("api_key must be nonempty without surrounding whitespace")
        if family.requires_credential and api_key is None:
            raise ValueError(f"{family.label} acquisition requires an explicit API key")
        self.family = family
        self._budget = budget
        self._key = api_key
        headers = {}
        if api_key and family.credential_header:
            headers[family.credential_header] = family.credential_format.format(key=api_key)
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=f"spicy-docs-{family.name}/1.0",
            label=family.label,
            error_type=PagedJsonSourceError,
            context_key="paged_json_acquisition",
            transport=transport,
            clock=clock,
            headers=headers,
            keyless=api_key is None,
            credential=api_key,
        )

    @property
    def budget(self) -> PagedJsonBudget:
        return self._budget

    def _continuation(
        self, value: Mapping[str, Any], *, url: str, body: Mapping[str, Any] | None, rows: list
    ) -> tuple[str | None, Mapping[str, Any] | None]:
        family = self.family
        if family.next_kind == "url":
            next_url = _lookup(value, family.next_path or ())
            if next_url is None:
                return None, None
            if not isinstance(next_url, str) or not next_url:
                raise PagedJsonSourceError(f"{family.label} continuation is invalid")
            next_url = family.check_url(next_url)
            if next_url == url:
                raise PagedJsonSourceError(f"{family.label} repeated its continuation")
            return next_url, None
        if family.next_kind == "page-number":
            next_page = _lookup(value, family.next_path or ())
            if next_page is None or next_page is False:
                return None, None
            if family.method == "POST":
                current = (body or {}).get(family.page_field)
            else:
                current_value = query_value(url, family.page_field)
                current = int(current_value) if current_value is not None and current_value.isdigit() else None
            if next_page is True:
                # A has-next flag names no page; the next page is one past the page requested.
                if current is None:
                    raise PagedJsonSourceError(f"{family.label} has-next flag needs an explicit {family.page_field}")
                next_page = current + 1
            if isinstance(next_page, bool) or not isinstance(next_page, int) or next_page < 1:
                raise PagedJsonSourceError(f"{family.label} continuation page number is invalid")
            if current is not None and next_page <= current:
                raise PagedJsonSourceError(f"{family.label} continuation page number does not advance")
            if family.method == "POST":
                return url, {**(body or {}), family.page_field: next_page}
            return with_query(url, family.page_field, str(next_page)), None
        limit_value = query_value(url, family.limit_field)
        offset_value = query_value(url, family.offset_field)
        if limit_value is None or not limit_value.isdigit() or int(limit_value) < 1:
            raise PagedJsonSourceError(f"{family.label} offset walk requires an explicit positive {family.limit_field}")
        if offset_value is None or not offset_value.isdigit():
            raise PagedJsonSourceError(f"{family.label} offset walk requires an explicit {family.offset_field}")
        limit, offset = int(limit_value), int(offset_value)
        if len(rows) > limit:
            raise PagedJsonSourceError(f"{family.label} returned more rows than its {family.limit_field}")
        if len(rows) < limit:
            return None, None
        return with_query(url, family.offset_field, str(offset + len(rows))), None

    def _reachable(self, url: str, body: Mapping[str, Any] | None) -> int:
        """Whole pages within the cap: a page size of 7 reaches 9,996 of a 10,000-record bound."""
        cap = self.family.max_reachable_records or 0
        value = (
            (body or {}).get(self.family.limit_field)
            if self.family.method == "POST"
            else query_value(url, self.family.limit_field)
        )
        size = int(value) if value is not None and str(value).isdigit() and int(value) > 0 else None
        return cap // size * size if size else cap

    def _read_page(
        self,
        capture: CapturedBodyResponse,
        *,
        url: str,
        body: Mapping[str, Any] | None,
        records_key: str | tuple[str, ...],
        page_index: int,
        single_record: bool,
    ) -> JsonPage:
        value = load_decimal_json(capture.body, source=self.family.label, error_type=PagedJsonSourceError)
        if not isinstance(value, Mapping):
            raise PagedJsonSourceError(f"{self.family.label} list response is not a JSON object")
        rows = _lookup(value, records_key) if isinstance(records_key, tuple) else value.get(records_key)
        if single_record and isinstance(rows, Mapping) and rows:
            # A detail route answers one record, not a list -- Congress.gov's law, committee,
            # member, house-communication, daily-congressional-record, senate-communication and
            # house-requirement detail routes all nest a single, non-empty object under their
            # records key rather than an array (measured 2026-09-19; its sibling treaty detail
            # route nests a one-element array instead, which the list branch below already
            # reads). Reading it as a one-row page keeps every field reachable through the same
            # records()/page() walk a list route uses, with no continuation and no declared
            # count, rather than being shaped down to one field. An *empty* object stays a
            # refusal, unchanged from before this route shape existed: empty success is not
            # absence, and a detail route answering ``{}`` carries no record to read.
            #
            # This wrapping is opt-in (``single_record``), not a blanket rule for every family
            # this reader serves: without it, a caller's wrong or mismatched ``records_key`` that
            # happens to resolve to a wrapper object -- Congress.gov's own
            # ``committee/{chamber}/{code}/bills`` answers a string key ``"committee-bills"`` as
            # ``{"bills": [...], "count": N, "url": "..."}`` -- would silently read as one bogus
            # record (the wrapper itself) instead of refusing. Not every family even has a
            # ``count_path`` to catch that downstream: FCC ECFS states no count at all and
            # regulations.gov's is advisory, so nothing would notice.
            rows = [rows]
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise PagedJsonSourceError(f"{self.family.label} list response omitted its {_key_label(records_key)} list")
        count = _lookup(value, self.family.count_path) if self.family.count_path else None
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            raise PagedJsonSourceError(f"{self.family.label} declared count is invalid")
        next_url, next_body = self._continuation(value, url=url, body=body, rows=rows)
        return JsonPage(page_index, records_key, capture, tuple(rows), count, next_url, body, next_body)

    def page(
        self,
        url: str,
        *,
        records_key: str | tuple[str, ...],
        page_index: int = 0,
        body: Mapping[str, Any] | None = None,
        single_record: bool = False,
    ) -> JsonPage:
        """Capture one list page and read its rows, declared count and continuation.

        ``single_record`` states a fact about the JSON at ``records_key`` -- a
        non-empty object rather than an array -- and opts into reading it as the
        page's one row instead of refusing it as a malformed list; it says nothing
        about how many records the query answers, since a one-element array already
        reads through the ordinary list path. It defaults to ``False`` so a wrong or
        mismatched ``records_key`` resolving to a wrapper object still refuses
        instead of silently reading that wrapper as a bogus record.
        """
        url = self.family.check_url(url)
        if (body is not None) != (self.family.method == "POST"):
            raise PagedJsonSourceError(
                f"{self.family.label} {self.family.method} pages "
                f"{'require' if self.family.method == 'POST' else 'forbid'} a request body"
            )
        content = _encode_body(body) if body is not None else None
        if content is not None and self._key and self._key.encode() in content:
            raise PagedJsonSourceError(f"{self.family.label} request body must not carry the credential")
        page, _capture = self.capture_validated(
            url,
            media_types=self.family.media_types,
            parse=lambda capture, _limit: self._read_page(
                capture,
                url=url,
                body=body,
                records_key=records_key,
                page_index=page_index,
                single_record=single_record,
            ),
            max_bytes=self.budget.max_page_bytes,
            unavailable=PagedJsonUnavailableError,
            context={
                "operation": "page",
                "family": self.family.name,
                "url": url,
                "requestBody": dict(body) if body is not None else None,
                "pageIndex": page_index,
                "recordsKey": records_key,
                "singleRecord": single_record,
            },
            method=self.family.method,
            content=content,
            request_headers={"Content-Type": "application/json"} if content is not None else None,
        )
        return page

    def _count_is_exact(self, url: str, declared_count: int | None) -> bool:
        """Whether the selected operation promises an exact count for its first response."""
        return self.family.count_kind == "exact"

    def pages(
        self,
        url: str,
        *,
        records_key: str | tuple[str, ...],
        max_pages: int = DEFAULT_MAX_PAGES,
        body: Mapping[str, Any] | None = None,
        single_record: bool = False,
    ) -> Iterator[JsonPage]:
        """Follow the publisher's continuations from the first request; refuse to end early or inconsistently.

        Pages already yielded remain partial observations when a later page refuses;
        only normal exhaustion means the traversal reached the publisher's terminal
        page. Exact-count operations must also agree with their declared total; an
        offset walk ends at the first short page with no declared count to check. ``single_record`` is forwarded to ``page()``.
        """
        check_request_count(max_pages, "max_pages")
        url = self.family.check_url(url)
        exact = self.family.count_kind == "exact"
        seen: set[tuple[str, bytes | None]] = set()
        declared: int | None = None
        observed = 0
        index = 0

        def traced(error: PagedJsonSourceError) -> PagedJsonSourceError:
            # Traversal refusals explain themselves the way page refusals do.
            error.__dict__[self.context_key] = {
                "operation": "traversal",
                "family": self.family.name,
                "url": url,
                "requestBody": dict(body) if body is not None else None,
                "pageIndex": index,
                "recordsKey": records_key,
                "singleRecord": single_record,
                "observedCount": observed,
                "declaredCount": declared,
            }
            return error

        def refuse(message: str) -> PagedJsonSourceError:
            return traced(PagedJsonSourceError(f"{self.family.label} {message}"))

        for index in range(max_pages):
            request = (url, _encode_body(body) if body is not None else None)
            if request in seen:
                raise refuse("repeated its continuation")
            seen.add(request)
            page = self.page(url, records_key=records_key, page_index=index, body=body, single_record=single_record)
            if index == 0:
                exact = self._count_is_exact(url, page.declared_count)
            if page.declared_count is not None:
                if declared is None:
                    declared = page.declared_count
                elif exact and page.declared_count != declared:
                    raise traced(
                        DeclaredCountChanged(
                            f"{self.family.label} declared count changed during the traversal",
                            declared=declared,
                            changed_to=page.declared_count,
                        )
                    )
            observed += len(page.records)
            if exact and declared is not None and observed > declared:
                raise refuse("returned more records than it declared")
            if index == 0 and self.family.max_reachable_records is not None and page.declared_count is not None:
                reachable = self._reachable(url, body)
                if page.declared_count > reachable:
                    error = refuse(
                        f"declares {page.declared_count} records but a walk reaches at most {reachable}; "
                        f"narrow the {self.family.window_hint} until the declared total fits"
                    )
                    error.__dict__["first_page"] = page
                    raise error
            yield page
            if page.next_url is None:
                if exact and declared is not None and observed != declared:
                    raise traced(
                        DeclaredCountMismatch(
                            f"{self.family.label} declared and observed record counts differ",
                            declared=declared,
                            observed=observed,
                        )
                    )
                return
            bound = self.family.max_page_number
            if bound is not None and self.family.next_kind == "page-number":
                next_number = (
                    (page.next_body or {}).get(self.family.page_field)
                    if page.next_body
                    else query_value(page.next_url, self.family.page_field)
                )
                if next_number is not None and int(next_number) > bound:
                    raise refuse(f"{self.family.page_field} bound {bound} reached with a next page outstanding")
            url, body = page.next_url, page.next_body
        raise refuse("page bound reached before a terminal response")


def family_with(family: JsonPageFamily, **changes: object) -> JsonPageFamily:
    """A publisher variant (another endpoint's row key or method) without restating the contract."""
    return replace(family, **changes)


@dataclass(frozen=True, slots=True)
class WalkPass:
    """One whole walk of a query: every record it served, in order, and the total the publisher declared for it."""

    records: tuple[Mapping[str, Any], ...]
    declared: int

    def __post_init__(self) -> None:
        if isinstance(self.declared, bool) or not isinstance(self.declared, int) or self.declared < 0:
            raise ValueError("declared must be a non-negative integer")

    @classmethod
    def from_pages(cls, pages: Iterable[JsonPage]) -> WalkPass:
        """Consume one walk's pages; its declared total is the one they state, which ``pages()`` holds constant."""
        records: list[Mapping[str, Any]] = []
        declared: int | None = None
        for page in pages:
            records.extend(page.records)
            if page.declared_count is not None:
                declared = page.declared_count
        if declared is None:
            raise PagedJsonSourceError("a pooled walk needs a declared total, and no page of this walk stated one")
        return cls(tuple(records), declared)


@dataclass(frozen=True, slots=True)
class PooledWalk:
    """What pooled walks settled on: one record per identity, its newest version, first-observed first."""

    records: tuple[Mapping[str, Any], ...]
    declared: int
    passes: int


def _identity(value: object, label: str) -> Hashable:
    """A key, never a record: a nonempty string, an integer, or a nonempty tuple of them.

    A missing or blank identity refuses rather than collapsing every such record into one.
    """
    parts = value if isinstance(value, tuple) else (value,)
    if not parts or not all(
        (isinstance(part, str) and part.strip()) or (isinstance(part, int) and not isinstance(part, bool))
        for part in parts
    ):
        raise PagedJsonSourceError(f"{label} served a record without a usable identity key")
    return value


def _stamp(version: Callable[[Mapping[str, Any]], Any], record: Mapping[str, Any], label: str) -> Any:
    """A record's version; one that cannot be read, or is ``None``, refuses rather than ranking arbitrarily."""
    try:
        value = version(record)
    except (KeyError, TypeError) as error:
        raise PagedJsonSourceError(f"{label} could not read a record's version") from error
    if value is None:
        raise PagedJsonSourceError(f"{label} served a record with no version")
    return value


def pool_walks(
    walk: Callable[[int], WalkPass],
    *,
    key: Callable[[Mapping[str, Any]], Hashable],
    version: Callable[[Mapping[str, Any]], Any] | None = None,
    max_passes: int = DEFAULT_POOL_PASSES,
    label: str,
) -> PooledWalk:
    """Repeat whole walks of one query, keyed by ``key``, until one is clean or they pool to the declared total.

    ``walk(index)`` runs pass ``index`` (from 0) to its terminal page; a caller
    alternates the order by index where the publisher honors it
    (``CongressListingReader.pooled``). ``version`` ranks one identity's
    observations -- the greatest is kept, a tie going to the later one --
    and must give a non-``None`` value that compares; without it the latest
    observation wins. The settling rules and their known limit are the
    module docstring's. Each pass is O(records) and at most ``max_passes``
    run; a query that does not settle raises ``IncompleteWalkError``.

    ``key`` names what identifies a record, never its content: a key over the
    whole record never settles once records carry fields that change between
    walks. FCC ECFS proceedings do (``last_30_days``, ``total_filing_count``)
    and one ``id_proceeding`` can carry more than one document, so key them by
    content that excludes the changing fields.
    """
    if isinstance(max_passes, bool) or not isinstance(max_passes, int) or max_passes < 1:
        raise ValueError("max_passes must be a positive integer")
    pool: dict[Hashable, tuple[Mapping[str, Any], Any]] = {}
    pooled_total: int | None = None  # the declared total the pool was gathered under
    stated = 0  # the latest total the publisher stated
    restarted = 0
    for index in range(max_passes):
        try:
            walked = walk(index)
        except DeclaredCountChanged as error:
            # The population moved under this pass: spend it, and pool afresh from the next.
            pool.clear()
            pooled_total, stated = None, error.changed_to
            restarted += 1
            continue
        if not isinstance(walked, WalkPass):
            raise TypeError("walk must return a WalkPass")
        stated = walked.declared
        if stated != pooled_total:
            pool.clear()
            pooled_total = stated
        observed: dict[Hashable, None] = {}  # this pass's identities, first-observed first
        for record in walked.records:
            identity = _identity(key(record), label)
            observed[identity] = None
            stamp = None if version is None else _stamp(version, record, label)
            held = pool.get(identity)
            if held is not None and version is not None:
                try:
                    older = stamp < held[1]
                except TypeError as error:
                    raise PagedJsonSourceError(f"{label} served versions that do not compare") from error
                if older:
                    continue
            pool[identity] = (record, stamp)
        if len(observed) == len(walked.records) == stated:
            return PooledWalk(tuple(pool[identity][0] for identity in observed), stated, index + 1)
        if len(pool) == stated:
            return PooledWalk(tuple(record for record, _ in pool.values()), stated, index + 1)
    raise IncompleteWalkError(label, declared=stated, distinct=len(pool), passes=max_passes, restarted=restarted)
