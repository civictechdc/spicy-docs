"""Explicit Congress.gov v3 list operations, page by page with exact evidence.

Every Congress.gov list route shares one shape -- a JSON page with its rows
under a named key, a ``pagination.count`` and a ``pagination.next`` URL -- so
one table, ``LIST_ROUTES``, states each route as data (its path template,
records key, which of its trailing path parameters are optional, and whether
the publisher honors ``sort`` and a ``fromDateTime``/``toDateTime`` window) and
one path builder, ``list_route_url``, plus ``CongressListingReader.records``,
build and walk any of them. ``bill_list_url``, ``crs_report_list_url`` and the
reader's ``bills``/``crs_reports`` methods are the original, named entry
points, now delegating with unchanged contracts; the api.data.gov key travels
as ``X-Api-Key``, and the walk runs to the publisher's terminal page or
refuses. A count is the publisher's statement for that query on that day, not
a frozen inventory.

Sort support is measured, not assumed, for every route: only ``bill``,
``amendment``, ``summaries``, ``committee-report`` and ``committee`` reorder
on ``sort=updateDate``, and direct probes found ``committee-bills``,
``bill-actions`` and ``house-vote`` ignoring it, so ``list_route_url`` refuses
a ``sort`` argument on a route that ignores it instead of sending one that
would silently do nothing. ``crs_report_list_url`` is the one deliberate
exception, predating the measurement: it keeps sending ``sort`` rather than
newly refuse a call that has always worked.

Date-window support (``window_honored``) got the same direct probe: a
one-day-old window cut ``committee-bills``' declared count (honored) while
leaving ``bill-actions`` at 59 either way (ignored). Every other route
defaults to ``True`` as a carried-forward assumption, not a measurement --
unlike ``sort_honored``, which is measured for every route.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
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
    parameters. ``optional_params`` names the ones a caller may omit; they must
    be the template's *trailing* parameters, since omitting one also omits
    every parameter after it. A route with no optional parameters requires
    every one it names on every request, the way
    ``committee/{chamber}/{code}/bills`` and
    ``bill/{congress}/{type}/{number}/actions`` do -- the publisher has no bare
    listing for either. ``records_key`` is a tuple where the publisher nests
    the rows inside a wrapper object instead of the top level (confirmed live:
    ``committee/{chamber}/{code}/bills`` answers
    ``{"committee-bills": {"bills": [...]}}``).

    ``single_record`` states a fact about the JSON shape at ``records_key`` --
    "this route's records key holds an object, not an array" -- not a fact
    about how many records the route yields: ``treaty-detail`` and
    ``committee-print-detail`` are detail routes that answer exactly one
    record with ``single_record`` left at ``False``, because their one record
    arrives inside an array and the reader's ordinary list path reads it.
    ``sort_honored`` is measured for every route; ``window_honored`` is
    measured for ``committee-bills`` and ``bill-actions`` and a carried-forward
    default elsewhere (module docstring). Every detail route has no list to
    reorder or window against, so it carries both flags ``False`` on
    structural grounds, not a live probe.
    """

    name: str
    path: str
    records_key: str | tuple[str, ...]
    optional_params: frozenset[str] = frozenset()
    sort_honored: bool = False
    window_honored: bool = True
    single_record: bool = False

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
        if self.single_record and (self.sort_honored or self.window_honored):
            raise ValueError("single_record routes have no list to reorder or window; both flags must be False")


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
    # One hearing by jacket number, answered as a bare object under "hearing"
    # (measured 2026-09-19, hearing/119/house/64431; fixtures README). It is
    # where hearing_transcripts.event_id comes from: the record's
    # associatedMeeting.eventId, which the map's hearing->meeting edge resolved.
    "hearing-detail": CongressListRoute(
        "hearing-detail",
        "hearing/{congress}/{chamber}/{number}",
        "hearing",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
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
    # meetings, treaties, record, communications, requirements (A5, A6, A7, A10)
    #
    # Path shapes and records keys measured live 2026-09-19 against the API
    # (docs/research/closing-the-gaps-2026-09-19.md gaps A5, A6, A7, A10; see
    # the fixtures README for every probe). Every list route here was probed
    # directly (limit=3, sort=updateDate desc vs asc, comparing the first
    # record and the declared count) and ignores sort. window_honored got the
    # same direct probe (a bare request vs one day's fromDateTime) for
    # committee-meeting, treaty, daily-congressional-record and
    # senate-communication; house-requirement and
    # house-requirement-communications keep the dataclass default
    # (window_honored=True), a carried-forward assumption from bill/crsreport,
    # not a measurement -- see the module docstring. Detail routes
    # (*-detail, and house-requirement-communications' own detail-adjacent
    # sibling house-requirement-detail) answer one record identified by its
    # full path, not a list: sort_honored and window_honored are both False
    # by construction there, not by probe, since there is nothing to reorder
    # or window. Congress.gov spells a detail record's row two ways --
    # house-communication, daily-congressional-record, senate-communication
    # and house-requirement detail nest a single object under their key, and
    # each carries single_record=True to opt CongressListingReader into
    # reading it as a one-row page (reading/paged_json.py's _read_page,
    # only when that flag is set); treaty detail nests a one-element array
    # instead, which the reader's ordinary list path already reads, so it
    # keeps single_record's False default.
    "committee-meeting": CongressListRoute(
        "committee-meeting",
        "committee-meeting/{congress}/{chamber}",
        "committeeMeetings",
        optional_params=frozenset({"congress", "chamber"}),
        sort_honored=False,
        window_honored=True,
    ),
    "committee-meeting-detail": CongressListRoute(
        "committee-meeting-detail",
        "committee-meeting/{congress}/{chamber}/{eventId}",
        "committeeMeeting",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
    "treaty": CongressListRoute(
        "treaty",
        "treaty/{congress}",
        "treaties",
        optional_params=frozenset({"congress"}),
        sort_honored=False,
        window_honored=True,
    ),
    "treaty-detail": CongressListRoute(
        "treaty-detail",
        "treaty/{congress}/{number}",
        "treaty",
        sort_honored=False,
        window_honored=False,
    ),
    "daily-congressional-record": CongressListRoute(
        "daily-congressional-record",
        "daily-congressional-record/{volume}",
        "dailyCongressionalRecord",
        optional_params=frozenset({"volume"}),
        sort_honored=False,
        window_honored=False,
    ),
    "daily-congressional-record-detail": CongressListRoute(
        "daily-congressional-record-detail",
        "daily-congressional-record/{volume}/{issue}",
        "issue",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
    "house-communication-detail": CongressListRoute(
        "house-communication-detail",
        "house-communication/{congress}/{commtype}/{number}",
        "houseCommunication",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
    "senate-communication": CongressListRoute(
        "senate-communication",
        "senate-communication/{congress}",
        "senateCommunications",
        optional_params=frozenset({"congress"}),
        sort_honored=False,
        window_honored=False,
    ),
    "senate-communication-detail": CongressListRoute(
        "senate-communication-detail",
        "senate-communication/{congress}/{commtype}/{number}",
        "senateCommunication",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
    "house-requirement": CongressListRoute(
        "house-requirement",
        "house-requirement",
        "houseRequirements",
        sort_honored=False,
    ),
    "house-requirement-detail": CongressListRoute(
        "house-requirement-detail",
        "house-requirement/{number}",
        "houseRequirement",
        sort_honored=False,
        window_honored=False,
        single_record=True,
    ),
    "house-requirement-communications": CongressListRoute(
        "house-requirement-communications",
        "house-requirement/{number}/matching-communications",
        "matchingCommunications",
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
    # none has been probed the way committee-bills/bill-actions were.
    # "law-detail", "committee-detail" and "member-detail" answer a bare
    # object at records_key, not an array or a pagination wrapper -- there is
    # nothing to reorder or window against a single object, so both flags are
    # False on structural grounds, not a live measurement (see the class
    # docstring), and each carries single_record=True to opt
    # CongressListingReader into reading that object as its one row rather
    # than refusing it. "committee-print-detail" is different: the publisher
    # answers it with a real one-item array and a pagination.count of 1: both
    # sort_honored/window_honored flags are still False, because no
    # reordering or windowing is possible against a one-item array either,
    # but the shape itself needs no single_record opt-in -- the reader's
    # ordinary list path already reads a one-item array.
    "law": CongressListRoute(
        "law", "law/{congress}/{law_type}", BILLS_KEY, optional_params=frozenset({"law_type"}), sort_honored=False
    ),
    "law-detail": CongressListRoute(
        "law-detail",
        "law/{congress}/{law_type}/{number}",
        "bill",
        sort_honored=False,
        window_honored=False,
        single_record=True,
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
        single_record=True,
    ),
    "member": CongressListRoute("member", "member", "members", sort_honored=False),
    "member-congress": CongressListRoute(
        "member-congress", "member/congress/{congress}", "members", sort_honored=False
    ),
    "member-detail": CongressListRoute(
        "member-detail",
        "member/{bioguide_id}",
        "member",
        sort_honored=False,
        window_honored=False,
        single_record=True,
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
# House and Senate communication type codes, from the publisher's own endpoint documentation
# (github.com/LibraryOfCongress/api.congress.gov), not sampled: the shipped fixtures alone only
# ever carry "EC" and one "ML", nowhere near enough to infer a closed set from. The two chambers'
# enumerations differ -- the House has no "pom", the Senate has no "pt"/"ml" -- so each route
# validates against its own set, not a union; see the fixtures README for the source URLs,
# retrieval commits and digests.
_HOUSE_COMMUNICATION_TYPES = frozenset({"ec", "pm", "pt", "ml"})
_SENATE_COMMUNICATION_TYPES = frozenset({"ec", "pm", "pom"})
_COMMUNICATION_TYPES_BY_ROUTE: dict[str, frozenset[str]] = {
    "house-communication-detail": _HOUSE_COMMUNICATION_TYPES,
    "senate-communication-detail": _SENATE_COMMUNICATION_TYPES,
}
# One kwarg name per path-parameter token, and one validator per token,
# shared by every route so a parameter is checked in exactly one place.
_KWARG_FOR_PARAM = {
    "congress": "congress",
    "chamber": "chamber",
    "code": "committee_code",
    "type": "bill_type",
    "number": "number",
    "session": "session",
    "eventId": "event_id",
    "volume": "volume",
    "issue": "issue",
    "commtype": "communication_type",
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


def _communication_type_param(value: str | None, route_name: str) -> str:
    """Validated against the calling route's own chamber, not a House/Senate union.

    Not dispatched through ``_VALIDATE_PARAM``: every other token's valid values are the same
    regardless of which route names it, but ``commtype`` is not -- the House and Senate
    enumerations differ -- so ``_route_path`` calls this directly, keyed by ``route.name``,
    instead of through the single-argument dispatch table.
    """
    valid = _COMMUNICATION_TYPES_BY_ROUTE.get(route_name)
    if valid is None:
        raise PagedJsonSourceError(f"{route_name} has no known communication_type enumeration to validate against")
    if value not in valid:
        raise PagedJsonSourceError(f"communication_type must be one of {sorted(valid)} for {route_name}")
    return value


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
    "eventId": lambda value: _positive_int_param(value, "event_id"),
    "volume": lambda value: _positive_int_param(value, "volume"),
    "issue": lambda value: _positive_int_param(value, "issue"),
    # "commtype" is deliberately absent: its valid values depend on which route calls it (the
    # House and Senate communication type enumerations differ), so _route_path dispatches it
    # directly to _communication_type_param with the route's name, not through this
    # single-argument table.
    "law_type": _law_type_param,
    # A committee's systemCode is the same shape wherever a route names it;
    # reusing the validator keeps that one check in one place.
    "system_code": _committee_code_param,
    "bioguide_id": _bioguide_id_param,
}


def _route_path(route: CongressListRoute, values: Mapping[str, object]) -> str:
    """Fill ``route.path``'s placeholders from an explicit, validated values mapping.

    The one path-assembly routine every route and every builder in this
    module goes through. ``values`` is keyed by path *token* name (``congress``,
    ``chamber``, ``code``, ``type``, ``number``, ``session``, ``eventId``,
    ``volume``, ``issue``, ``commtype``, ``law_type``, ``system_code``,
    ``bioguide_id``) -- the same 13 names ``_KWARG_FOR_PARAM`` and
    ``_VALIDATE_PARAM`` state, not each caller's own public kwarg names.
    ``values`` must carry a key -- explicitly ``None`` where the caller has
    nothing to offer -- for every one of the route's own path tokens; a token
    missing from ``values`` entirely (as opposed to present and ``None``) is a
    caller bug and refuses here. A value for a parameter the route does not
    name is refused outright; an omitted optional parameter also omits every
    parameter after it, so ``bill``'s ``type`` without a ``congress`` refuses
    rather than silently addressing a different route.
    """
    params = set(route.path_params)
    missing = params - set(values)
    if missing:
        raise PagedJsonSourceError(f"{route.name} values mapping is missing {sorted(missing)}")
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
        value = values.get(name)
        if value is None:
            if name not in route.optional_params:
                raise PagedJsonSourceError(f"{route.name} requires an explicit {_KWARG_FOR_PARAM[name]}")
            stopped_at = stopped_at or name
            continue
        if stopped_at is not None:
            raise PagedJsonSourceError(f"{_KWARG_FOR_PARAM[name]} requires an explicit {_KWARG_FOR_PARAM[stopped_at]}")
        # "commtype" is the one token whose valid values depend on the route asking for it (the
        # House and Senate communication type enumerations differ), so it is dispatched directly
        # rather than through _VALIDATE_PARAM's single-argument table; see
        # _communication_type_param.
        if name == "commtype":
            segments.append(_communication_type_param(value, route.name))
        else:
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
    event_id: int | None = None,
    volume: int | None = None,
    issue: int | None = None,
    communication_type: str | None = None,
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
    # Built once here, from this function's own explicit 13-parameter signature, and forwarded
    # to _route_path as a single mapping rather than 13 repeated keyword arguments.
    values: dict[str, object] = {
        "congress": congress,
        "chamber": chamber,
        "code": committee_code,
        "type": bill_type,
        "number": number,
        "session": session,
        "eventId": event_id,
        "volume": volume,
        "issue": issue,
        "commtype": communication_type,
        "law_type": law_type,
        "system_code": system_code,
        "bioguide_id": bioguide_id,
    }
    path = _route_path(route, values)
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
    path = _route_path(LIST_ROUTES["bill"], {"congress": congress, "type": bill_type})
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
    path = _route_path(LIST_ROUTES["crsreport"], {})
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
        return self.pages(url, records_key=route.records_key, max_pages=max_pages, single_record=route.single_record)

    def bills(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.records(LIST_ROUTES["bill"], url, max_pages=max_pages)

    def crs_reports(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.records(LIST_ROUTES["crsreport"], url, max_pages=max_pages)
