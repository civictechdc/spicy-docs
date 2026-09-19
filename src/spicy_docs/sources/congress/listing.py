"""Explicit Congress.gov v3 list operations, page by page with exact evidence.

Every Congress.gov list route shares one shape -- a JSON page with its rows
under a named key, a ``pagination.count`` and a ``pagination.next`` URL -- so
one table, ``LIST_ROUTES``, states each route as data (its path template,
records key, which of its trailing path parameters are optional, and whether
the publisher honors ``sort`` and a ``fromDateTime``/``toDateTime`` window)
and one pair of functions, ``_route_path``/``list_route_url``, and one reader
method, ``CongressListingReader.records``, build and walk any of them.
``bill_list_url``, ``crs_report_list_url`` and the reader's
``bills``/``crs_reports`` methods are the original, named entry points for the
first two routes ported; they now delegate to the same table and the same
path builder rather than duplicating it, and their contracts (arguments,
defaults, return shapes) are unchanged. The api.data.gov key travels as
``X-Api-Key``. The walk runs to the publisher's terminal page or refuses. A
count is the publisher's statement for that query on that day, not a frozen
inventory.

Sort support is measured, not assumed, for every route in the table: a
2026-09-19 pass over the legislative data map
(``docs/research/legislative-data-map-2026-09-18.md`` Table A) found only
``bill``, ``amendment``, ``summaries``, ``committee-report`` and ``committee``
reorder on ``sort=updateDate``; a same-day direct probe of ``committee-bills``
and ``bill-actions`` (``limit=1``, ``sort=updateDate desc`` vs ``asc``,
comparing the first record) found both answer the identical first record
either way -- see the fixtures README for the four requests and responses.
Every other list answers the same row order regardless. ``list_route_url``
refuses a ``sort`` argument on a route that ignores it instead of sending one
that would silently do nothing. ``crs_report_list_url`` is the one deliberate
exception: it predates this measurement, already sent ``sort``
unconditionally, and keeps doing so rather than newly refuse a call that has
always worked -- a caller who wants the refusal uses
``list_route_url(LIST_ROUTES["crsreport"], ...)`` instead, and so does
``bill_list_url``/``crs_report_list_url`` themselves when handed a literal
``sort=None``, since that was never a legal value for either.

Date-window support (``window_honored``) is the same same-day probe applied to
``fromDateTime``: a one-day-old window against ``committee-bills`` cut its
declared count from 41,822 to 9 (honored), while the same window against
``bill-actions`` left the declared count at 59 either way (ignored) -- also in
the fixtures README. Every other route defaults to ``window_honored=True``:
``bill`` and ``crsreport`` have always accepted the window unconditionally
(the original, pre-existing contract this module preserves), and nothing has
surfaced evidence any of the other newly added routes ignore it. That default
is a carried-forward assumption, not a measurement, and is named as such --
unlike ``sort_honored``, which is now measured for every route.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode

from spicy_docs.reading.paged_json import (
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
)
from spicy_docs.sources.congress.bill_status import BILL_TYPES
from spicy_docs.transport.source_acquirer import utc_now

if TYPE_CHECKING:
    import httpx

API = "https://api.congress.gov/v3"
MAX_LIMIT = 250
BILLS_KEY = "bills"
CRS_REPORTS_KEY = "CRSReports"
type ListSort = Literal["updateDate asc", "updateDate desc"]
CONGRESS_GOV = JsonPageFamily(
    name="congress-gov",
    label="Congress.gov",
    host="api.congress.gov",
    next_path=("pagination", "next"),
    count_path=("pagination", "count"),
)
_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _datetime(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATETIME.fullmatch(value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid UTC datetime") from error
    return value


def _query(
    *, from_datetime: str | None, to_datetime: str | None, limit: int, sort: ListSort | None
) -> list[tuple[str, str]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise PagedJsonSourceError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if sort is not None and sort not in ("updateDate asc", "updateDate desc"):
        raise PagedJsonSourceError("sort must be 'updateDate asc' or 'updateDate desc'")
    start = _datetime(from_datetime, "from_datetime")
    end = _datetime(to_datetime, "to_datetime")
    if start is not None and end is not None and end < start:
        raise PagedJsonSourceError("to_datetime precedes from_datetime")
    query = [("format", "json"), ("limit", str(limit))]
    if sort is not None:
        query.append(("sort", sort))
    if start is not None:
        query.append(("fromDateTime", start))
    if end is not None:
        query.append(("toDateTime", end))
    return query


@dataclass(frozen=True, slots=True)
class CongressListRoute:
    """One Congress.gov list route: its path template, records key, and ``sort``/window support.

    Named ``CongressListRoute`` (not ``ListRoute``) because
    ``spicy_docs.cli.list_pages.ListRoute`` already names a different,
    publisher-agnostic route wrapper; the two would collide if a caller
    imported both.

    ``path`` is a ``/``-joined template whose ``{name}`` segments are path
    parameters (``congress``, ``chamber``, ``code``, ``type``, ``number``,
    ``session``, ``law_type``, ``system_code``, ``bioguide_id``).
    ``optional_params`` names the ones a caller may omit; they must be the
    template's *trailing* parameters, since omitting one also omits every
    parameter after it (a caller cannot narrow by bill type without naming a
    Congress). A route with no optional parameters requires every one it
    names on every request, the way ``committee/{chamber}/{code}/bills`` and
    ``bill/{congress}/{type}/{number}/actions`` do -- the publisher has no
    bare listing for either. ``sort_honored`` is measured for every route;
    ``window_honored`` is measured for ``committee-bills`` and
    ``bill-actions`` and a carried-forward default elsewhere: see the module
    docstring for both. ``records_key`` is a tuple where the publisher nests
    the rows inside a wrapper object instead of the top level -- confirmed
    live 2026-09-19: ``committee/{chamber}/{code}/bills`` answers
    ``{"committee-bills": {"bills": [...], "count": N, "url": "..."}, ...}``,
    not a top-level ``bills`` array, unlike every other route here. A detail
    route's ``records_key`` names a single JSON object instead of an array --
    ``law/{congress}/{law_type}/{number}`` answers ``{"bill": {...}}`` -- and
    ``PagedJsonReader`` reads that object as the walk's one record rather
    than shaping it down to a chosen field; a detail route also has no list
    to reorder or window, so it carries ``sort_honored=False`` and
    ``window_honored=False`` on structural grounds, not a live probe.
    """

    name: str
    path: str
    records_key: str | tuple[str, ...]
    optional_params: frozenset[str] = frozenset()
    sort_honored: bool = False
    window_honored: bool = True

    @property
    def path_params(self) -> tuple[str, ...]:
        return tuple(part[1:-1] for part in self.path.split("/") if part.startswith("{") and part.endswith("}"))

    def __post_init__(self) -> None:
        for field_name in ("name", "path"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a nonempty string")
        key = self.records_key
        valid_key = (isinstance(key, str) and key) or (
            isinstance(key, tuple) and key and all(isinstance(part, str) and part for part in key)
        )
        if not valid_key:
            raise ValueError("records_key must be a nonempty string or tuple of nonempty strings")
        params = self.path_params
        if not set(self.optional_params) <= set(params):
            raise ValueError("optional_params must be a subset of the route's path parameters")
        seen_optional = False
        for param in params:
            if param in self.optional_params:
                seen_optional = True
            elif seen_optional:
                raise ValueError("optional_params must be the path's trailing parameters")


# Path shapes and records keys measured 2026-09-19 against the live API
# (docs/research/legislative-data-map-2026-09-18.md). sort_honored is
# measured for every route: only bill, amendment, summaries, committee-report
# and committee reorder on sort; committee-bills, bill-actions and house-vote
# were probed directly the same day (see the module docstring and the
# fixtures README) and none of the three does. window_honored is measured
# only for committee-bills (True) and bill-actions (False); every other
# route keeps the default, which is a carried-forward assumption, not a
# measurement -- see the module docstring. "bill" keeps its historical
# bare-collection/Congress/type narrowing (both congress and type may be
# omitted, but type only follows congress); "committee-bills", "bill-actions"
# and "house-vote" have no bare collection at all. "house-vote"
# sort_honored=False is a direct probe of house-vote/119/1 (limit=1,
# sort=updateDate desc vs asc, comparing the first record; see the fixtures
# README), not only the earlier, indirect inference from its sibling
# `house-vote/{c}/{session}/{roll}/members` route.
LIST_ROUTES: dict[str, CongressListRoute] = {
    "bill": CongressListRoute(
        "bill", "bill/{congress}/{type}", BILLS_KEY, optional_params=frozenset({"congress", "type"}), sort_honored=True
    ),
    "crsreport": CongressListRoute("crsreport", "crsreport", CRS_REPORTS_KEY),
    "amendment": CongressListRoute(
        "amendment", "amendment/{congress}", "amendments", optional_params=frozenset({"congress"}), sort_honored=True
    ),
    "committee-bills": CongressListRoute(
        "committee-bills",
        "committee/{chamber}/{code}/bills",
        ("committee-bills", "bills"),
        sort_honored=False,
        window_honored=True,
    ),
    "bill-actions": CongressListRoute(
        "bill-actions",
        "bill/{congress}/{type}/{number}/actions",
        "actions",
        sort_honored=False,
        window_honored=False,
    ),
    "nomination": CongressListRoute(
        "nomination", "nomination/{congress}", "nominations", optional_params=frozenset({"congress"})
    ),
    "hearing": CongressListRoute("hearing", "hearing/{congress}", "hearings", optional_params=frozenset({"congress"})),
    "committee-report": CongressListRoute(
        "committee-report",
        "committee-report/{congress}",
        "reports",
        optional_params=frozenset({"congress"}),
        sort_honored=True,
    ),
    "house-communication": CongressListRoute(
        "house-communication",
        "house-communication/{congress}",
        "houseCommunications",
        optional_params=frozenset({"congress"}),
    ),
    "house-vote": CongressListRoute(
        "house-vote",
        "house-vote/{congress}/{session}",
        "houseRollCallVotes",
        sort_honored=False,
    ),
    # laws, committees, members, prints (A8, A9, A10)
    #
    # Path shapes and records keys measured live 2026-09-19 at limit=3 (see
    # the fixtures README). sort_honored for "law", "committee", "member" and
    # "committee-print" is carried from the legislative data map's Table A
    # (docs/research/legislative-data-map-2026-09-18.md), the same way
    # "nomination", "hearing", "committee-report" and "house-communication"
    # above carry theirs -- each is the exact route Table A measured, not a
    # sibling. "member-congress" answers a different URL than Table A's bare
    # "member" row, so it got the same direct probe "house-vote" did:
    # member/congress/119?limit=1, sort=updateDate desc vs asc, identical
    # first record (bioguideId W000832) either way -- sort ignored. Every
    # list route here keeps window_honored's carried-forward default (True);
    # none has been probed the way committee-bills/bill-actions were. The
    # four detail routes ("law-detail", "committee-detail", "member-detail",
    # "committee-print-detail") answer one record, not a list -- there is
    # nothing to reorder or window against a single record, so both flags are
    # False on structural grounds, not a live measurement (see the class
    # docstring).
    "law": CongressListRoute(
        "law", "law/{congress}/{law_type}", BILLS_KEY, optional_params=frozenset({"law_type"}), sort_honored=False
    ),
    "law-detail": CongressListRoute(
        "law-detail", "law/{congress}/{law_type}/{number}", "bill", sort_honored=False, window_honored=False
    ),
    "committee": CongressListRoute(
        "committee", "committee/{congress}", "committees", optional_params=frozenset({"congress"}), sort_honored=True
    ),
    "committee-detail": CongressListRoute(
        "committee-detail",
        "committee/{chamber}/{system_code}",
        "committee",
        sort_honored=False,
        window_honored=False,
    ),
    "member": CongressListRoute("member", "member", "members", sort_honored=False),
    "member-congress": CongressListRoute(
        "member-congress", "member/congress/{congress}", "members", sort_honored=False
    ),
    "member-detail": CongressListRoute(
        "member-detail", "member/{bioguide_id}", "member", sort_honored=False, window_honored=False
    ),
    "committee-print": CongressListRoute(
        "committee-print", "committee-print/{congress}", "committeePrints", sort_honored=False
    ),
    "committee-print-detail": CongressListRoute(
        "committee-print-detail",
        "committee-print/{congress}/{chamber}/{number}",
        "committeePrint",
        sort_honored=False,
        window_honored=False,
    ),
}

_CHAMBERS = frozenset({"house", "senate", "joint"})
_COMMITTEE_CODE = re.compile(r"[a-z]{4}[0-9]{2}")
_LAW_TYPES = frozenset({"pub", "priv"})
_BIOGUIDE_ID = re.compile(r"[A-Z][0-9]{6}")
# One kwarg name per path-parameter token, and one validator per token,
# shared by every route so a parameter is checked in exactly one place.
_KWARG_FOR_PARAM = {
    "congress": "congress",
    "chamber": "chamber",
    "code": "committee_code",
    "type": "bill_type",
    "number": "number",
    "session": "session",
    "law_type": "law_type",
    "system_code": "system_code",
    "bioguide_id": "bioguide_id",
}


def _chamber_param(value: str | None) -> str:
    if value not in _CHAMBERS:
        raise PagedJsonSourceError("chamber must be 'house', 'senate' or 'joint'")
    return value


def _committee_code_param(value: str | None) -> str:
    if not isinstance(value, str) or _COMMITTEE_CODE.fullmatch(value) is None:
        raise PagedJsonSourceError("committee_code must match [a-z]{4}[0-9]{2}")
    return value


def _bill_type_param(value: str | None) -> str:
    if value not in BILL_TYPES:
        raise PagedJsonSourceError("bill_type must be a supported lowercase bill or resolution type")
    return value


def _positive_int_param(value: int | None, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PagedJsonSourceError(f"{name} must be a positive integer")
    return str(value)


def _congress_param(value: int | None) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 999:
        raise PagedJsonSourceError("congress must be an integer from 1 to 999")
    return str(value)


def _session_param(value: int | None) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2):
        raise PagedJsonSourceError("session must be 1 or 2")
    return str(value)


def _law_type_param(value: str | None) -> str:
    if value not in _LAW_TYPES:
        raise PagedJsonSourceError("law_type must be 'pub' or 'priv'")
    return value


def _bioguide_id_param(value: str | None) -> str:
    if not isinstance(value, str) or _BIOGUIDE_ID.fullmatch(value) is None:
        raise PagedJsonSourceError("bioguide_id must match [A-Z][0-9]{6}")
    return value


_VALIDATE_PARAM: dict[str, Callable[[object], str]] = {
    "congress": _congress_param,
    "chamber": _chamber_param,
    "code": _committee_code_param,
    "type": _bill_type_param,
    "number": lambda value: _positive_int_param(value, "number"),
    "session": _session_param,
    "law_type": _law_type_param,
    # A committee's systemCode is the same shape wherever a route names it;
    # reusing the validator keeps that one check in one place.
    "system_code": _committee_code_param,
    "bioguide_id": _bioguide_id_param,
}


def _route_path(
    route: CongressListRoute,
    *,
    congress: int | None = None,
    chamber: str | None = None,
    committee_code: str | None = None,
    bill_type: str | None = None,
    number: int | None = None,
    session: int | None = None,
    law_type: str | None = None,
    system_code: str | None = None,
    bioguide_id: str | None = None,
) -> str:
    """Fill ``route.path``'s placeholders from explicit, validated parameters.

    The one path-assembly routine every route and every builder in this
    module goes through. A value for a parameter the route does not name is
    refused outright; an omitted optional parameter also omits every
    parameter after it, so ``bill``'s ``bill_type`` without a ``congress``
    refuses rather than silently addressing a different route.
    """
    values: dict[str, object] = {
        "congress": congress,
        "chamber": chamber,
        "code": committee_code,
        "type": bill_type,
        "number": number,
        "session": session,
        "law_type": law_type,
        "system_code": system_code,
        "bioguide_id": bioguide_id,
    }
    params = set(route.path_params)
    for name, value in values.items():
        if value is not None and name not in params:
            raise PagedJsonSourceError(f"{route.name} does not take a {_KWARG_FOR_PARAM[name]}")
    segments: list[str] = []
    stopped_at: str | None = None
    for part in route.path.split("/"):
        if not (part.startswith("{") and part.endswith("}")):
            segments.append(part)
            continue
        name = part[1:-1]
        value = values[name]
        if value is None:
            if name not in route.optional_params:
                raise PagedJsonSourceError(f"{route.name} requires an explicit {_KWARG_FOR_PARAM[name]}")
            stopped_at = stopped_at or name
            continue
        if stopped_at is not None:
            raise PagedJsonSourceError(f"{_KWARG_FOR_PARAM[name]} requires an explicit {_KWARG_FOR_PARAM[stopped_at]}")
        segments.append(_VALIDATE_PARAM[name](value))
    return "/".join(segments)


def list_route_url(
    route: CongressListRoute,
    *,
    congress: int | None = None,
    chamber: str | None = None,
    committee_code: str | None = None,
    bill_type: str | None = None,
    number: int | None = None,
    session: int | None = None,
    law_type: str | None = None,
    system_code: str | None = None,
    bioguide_id: str | None = None,
    from_datetime: str | None = None,
    to_datetime: str | None = None,
    limit: int = MAX_LIMIT,
    sort: ListSort | None = None,
) -> str:
    """Name one query on any ``LIST_ROUTES`` entry; refuses ``sort`` or a date window a route does not honor."""
    if not isinstance(route, CongressListRoute):
        raise TypeError("route must be a CongressListRoute")
    if sort is not None and not route.sort_honored:
        raise PagedJsonSourceError(f"{route.name} route: Congress.gov ignores sort here; omit it")
    if not route.window_honored and (from_datetime is not None or to_datetime is not None):
        raise PagedJsonSourceError(
            f"{route.name} route: Congress.gov ignores the date window here; omit from_datetime/to_datetime"
        )
    path = _route_path(
        route,
        congress=congress,
        chamber=chamber,
        committee_code=committee_code,
        bill_type=bill_type,
        number=number,
        session=session,
        law_type=law_type,
        system_code=system_code,
        bioguide_id=bioguide_id,
    )
    query = _query(from_datetime=from_datetime, to_datetime=to_datetime, limit=limit, sort=sort)
    return f"{API}/{path}?{urlencode(query)}"


def _required_sort(sort: object) -> ListSort:
    """``bill_list_url``/``crs_report_list_url`` have never accepted a missing sort, unlike
    ``list_route_url``'s optional one; a literal ``sort=None`` refuses here exactly as it always has."""
    if sort not in ("updateDate asc", "updateDate desc"):
        raise PagedJsonSourceError("sort must be 'updateDate asc' or 'updateDate desc'")
    return sort


def bill_list_url(
    *,
    congress: int | None = None,
    bill_type: str | None = None,
    from_datetime: str | None = None,
    to_datetime: str | None = None,
    limit: int = MAX_LIMIT,
    sort: ListSort = "updateDate desc",
) -> str:
    """Name one bill list query; a bill type requires its Congress."""
    path = _route_path(LIST_ROUTES["bill"], congress=congress, bill_type=bill_type)
    query = _query(from_datetime=from_datetime, to_datetime=to_datetime, limit=limit, sort=_required_sort(sort))
    return f"{API}/{path}?{urlencode(query)}"


def crs_report_list_url(
    *,
    from_datetime: str | None = None,
    to_datetime: str | None = None,
    limit: int = MAX_LIMIT,
    sort: ListSort = "updateDate desc",
) -> str:
    """Name one CRS report list query.

    ``crsreport`` does not reorder on ``sort`` (measured 2026-09-19, see the
    module docstring); this wrapper predates that measurement and keeps
    sending ``sort`` unconditionally rather than newly refuse a call that has
    always worked.
    """
    path = _route_path(LIST_ROUTES["crsreport"])
    query = _query(from_datetime=from_datetime, to_datetime=to_datetime, limit=limit, sort=_required_sort(sort))
    return f"{API}/{path}?{urlencode(query)}"


class CongressListingReader(PagedJsonReader):
    """Every Congress.gov list route; every page is one bounded, evidenced request."""

    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=CONGRESS_GOV, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def records(self, route: CongressListRoute, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk any ``LIST_ROUTES`` entry's pages, keyed the way its publisher spells its rows."""
        if not isinstance(route, CongressListRoute):
            raise TypeError("route must be a CongressListRoute")
        return self.pages(url, records_key=route.records_key, max_pages=max_pages)

    def bills(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.records(LIST_ROUTES["bill"], url, max_pages=max_pages)

    def crs_reports(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.records(LIST_ROUTES["crsreport"], url, max_pages=max_pages)
