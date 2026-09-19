"""House Clerk ``MemberData.xml`` and Senate ``cvc_member_data.xml``: the current committee assignments.

Congress.gov's ``committee`` and ``member`` routes are the rosters of record
for identity and history (the legislative data map's comparison: the API
lists everyone who served in the 119th, 555; the chamber files list the 541
seats filled today, and every one of the 14 API-only members has an ended
term -- rerun 2026-09-19 in
``corpora/supply-2026-09-02/receipts/roster-comparison-2026-09-19/``). The
chamber files add exactly two things the API does not carry: **which member
sits on which committee today**, and, for the Senate, the LIS id beside the
bioguide. This module reads the assignments; the LIS crosswalk stays
``sources/legislators.py`` (the only route to a *former* senator's LIS id),
which is why nothing here builds a second one.

Two unrelated XML grammars, measured 2026-09-19 (556,936 and 67,618 bytes):

* **House.** ``<MemberData publish-date="September 2, 2026">`` with a
  ``<title-info>`` stating ``congress-num``, ``congress-text``, ``session``,
  ``majority``, ``minority``, ``clerk`` and ``weburl``; 441 ``<member>``
  elements, each with ``statedistrict``, a ``member-info`` block (bioguide
  under ``bioguideID``, names, party, caucus, state, district, office,
  elected and sworn dates) and ``committee-assignments`` of
  ``<committee comcode="II00" rank="22" [leadership="Vice Chair"]/>`` and
  ``<subcommittee subcomcode="II06" rank="13"/>``; then a ``<committees>``
  block naming all 27 committees and 109 subcommittees by code with their
  full names and party ratios. Two of the 441 are **vacancies**: every
  ``member-info`` field empty and one ``<committee rank=""/>`` placeholder.
  Nine members carry that same placeholder as their only assignment. A
  placeholder is "no assignment", not a malformed row, so it is counted and
  skipped rather than refused. Leadership values seen: ``Chair``,
  ``Chairman``, ``Chairwoman``, ``Vice Chair``, ``Vice Chairman``,
  ``Vice Chairwoman`` -- kept verbatim.
* **Senate.** ``<senators>`` with one ``<lastUpdate>`` (``date`` and
  ``time``) and 100 ``<senator lis_member_id="S428">`` elements, each
  stating ``bioguideId``, name parts, party, state, ``stateRank``, office,
  an optional ``leadership_position`` and ``<committee code="SSAS00"
  [position="Chairman"]>`` children whose text is the committee's name.
  Positions seen: ``Chairman``, ``Ranking``, ``Vice Chairman``. **The file
  states no Congress and no session**, only its update date; the House file
  states both.

**Identity proof.** :func:`parse_house_member_data` takes the Congress (and
optionally the session) the caller requested and checks the file's own
``congress-num``/``session`` against it before any member is read. The
Senate file cannot be proved that way because it states no Congress, so
:func:`parse_senate_cvc` proves only what the file states -- its root, its
update date, and that every senator carries both ids -- and the assignment
row a caller shapes from it says so (``congress_basis = "caller"``).

**System codes.** The map proved the join to Congress.gov's ``systemCode``
on both files: House ``comcode II00`` is ``hsii00`` (edge
``memberdata→committee``), Senate ``SPAG00`` is ``spag00`` (``cvc→committee``).
:func:`house_system_code` and :func:`senate_system_code` are those two
rules; the Senate file's codes already end in ``00`` (27 of 27), so its rule
is a lowercase and nothing more.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element

from spicy_docs.reading.rss import child_text, single_child
from spicy_docs.reading.xml import parse_xml
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    named_challenge,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    from datetime import datetime

    import httpx

HOUSE_MEMBER_DATA_URL = "https://clerk.house.gov/xml/lists/MemberData.xml"
SENATE_CVC_URL = "https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml"
MEDIA_TYPES = ("text/xml", "application/xml")

# Measured 2026-09-19: MemberData.xml 556,936 bytes, cvc_member_data.xml 67,618 bytes.
DEFAULT_MAX_HOUSE_BYTES = 4 * 1024**2
DEFAULT_MAX_SENATE_BYTES = 1 * 1024**2
MAX_ROSTER_BYTES = 16 * 1024**2

_HOUSE_INFO_FIELDS = (
    "namelist",
    "lastname",
    "firstname",
    "middlename",
    "sort-name",
    "suffix",
    "courtesy",
    "prior-congress",
    "official-name",
    "formal-name",
    "party",
    "caucus",
    "district",
    "townname",
    "office-building",
    "office-room",
    "office-zip",
    "office-zip-suffix",
    "phone",
)


class CommitteeRosterError(ValueError):
    """The response cannot establish a chamber roster file."""


class CommitteeRosterUnavailableError(CommitteeRosterError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"chamber roster source answered HTTP {capture.status_code}")
        self.capture = capture


class CommitteeRosterRefusedError(CommitteeRosterError):
    """A keyless route answered 401/403; there is no credential here to reject."""

    def __init__(self, url: str) -> None:
        super().__init__(f"chamber roster source refused access to {url}; no credential exists to reject")
        self.url = url


class CommitteeRosterIdentityError(CommitteeRosterError):
    """The House file states another Congress or session than the caller requested."""

    def __init__(self, *, requested: tuple[int, int | None], stated: tuple[int, int | None]) -> None:
        super().__init__(f"MemberData.xml states congress/session {stated}, not the requested {requested}")
        self.requested = requested
        self.stated = stated


def house_system_code(comcode: str) -> str:
    """``II00`` -> ``hsii00``, ``II06`` -> ``hsii06``: the map's ``memberdata→committee`` rule."""
    code = comcode.strip().lower()
    if not code:
        raise CommitteeRosterError("a House committee code cannot be empty")
    return code if code.startswith("hs") else f"hs{code}"


def senate_system_code(code: str) -> str:
    """``SPAG00`` -> ``spag00``: the map's ``cvc→committee`` rule; every file code already ends in ``00``."""
    value = code.strip().lower()
    if not value:
        raise CommitteeRosterError("a Senate committee code cannot be empty")
    return value if value.endswith("00") else f"{value}00"


@dataclass(frozen=True, slots=True)
class HouseAssignment:
    """One ``<committee>`` or ``<subcommittee>`` under a member's assignments."""

    code: str
    kind: str  # "committee" | "subcommittee"
    rank: str | None
    leadership: str | None

    @property
    def system_code(self) -> str:
        return house_system_code(self.code)


@dataclass(frozen=True, slots=True)
class HouseMember:
    """One ``<member>`` seat. A vacancy has ``bioguide_id`` ``None`` and every name field empty."""

    state_district: str
    bioguide_id: str | None
    state_code: str | None
    state_name: str | None
    fields: Mapping[str, str | None]
    elected_date: str | None
    sworn_date: str | None
    assignments: tuple[HouseAssignment, ...]
    placeholder_assignments: int

    @property
    def vacant(self) -> bool:
        return self.bioguide_id is None


@dataclass(frozen=True, slots=True)
class HouseSubcommittee:
    code: str
    name: str
    majority: str | None
    minority: str | None
    attributes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class HouseCommittee:
    """One entry of the file's own ``<committees>`` block: the names the assignment codes resolve to."""

    code: str
    name: str
    type: str | None
    majority: str | None
    minority: str | None
    subcommittees: tuple[HouseSubcommittee, ...]
    attributes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class HouseMemberData:
    congress: int
    session: int | None
    congress_text: str | None
    publish_date: str | None
    majority: str | None
    minority: str | None
    clerk: str | None
    members: tuple[HouseMember, ...]
    committees: tuple[HouseCommittee, ...]
    committee_names: Mapping[str, str]
    parent_codes: Mapping[str, str]
    identity_basis: tuple[str, ...]

    @property
    def vacancies(self) -> int:
        return sum(1 for member in self.members if member.vacant)


@dataclass(frozen=True, slots=True)
class SenateCommitteeAssignment:
    code: str
    name: str
    position: str | None

    @property
    def system_code(self) -> str:
        return senate_system_code(self.code)


@dataclass(frozen=True, slots=True)
class Senator:
    lis_id: str
    bioguide_id: str
    prefix: str | None
    first: str | None
    last: str | None
    suffix: str | None
    party: str | None
    state: str | None
    home_town: str | None
    state_rank: str | None
    office: str | None
    leadership_position: str | None
    committees: tuple[SenateCommitteeAssignment, ...]


@dataclass(frozen=True, slots=True)
class SenateCvc:
    """The Senate file. It states an update date and no Congress; ``congress`` is therefore not a field."""

    last_update_date: str | None
    last_update_time: str | None
    senators: tuple[Senator, ...]
    identity_basis: tuple[str, ...] = ("root:native", "update-date:native")


def _text(element: Element, tag: str, label: str) -> str | None:
    return child_text(element, tag, error_type=CommitteeRosterError, label=label)


def _required(element: Element, tag: str, label: str) -> str:
    value = _text(element, tag, label)
    if value is None:
        raise CommitteeRosterError(f"{label} is missing <{tag}>")
    return value


def _int(value: str, label: str, field: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise CommitteeRosterError(f"{label} {field} is not an integer: {value!r}") from None


def _read_house_assignments(element: Element | None, label: str) -> tuple[tuple[HouseAssignment, ...], int]:
    assignments: list[HouseAssignment] = []
    placeholders = 0
    for child in element if element is not None else ():
        if child.tag == "committee":
            code = child.get("comcode")
        elif child.tag == "subcommittee":
            code = child.get("subcomcode")
        else:
            raise CommitteeRosterError(f"{label} committee-assignments carries an unknown <{child.tag}>")
        if not code:
            # ``<committee rank=""/>``: the file's spelling of "no assignment",
            # on every vacancy and on nine seated members (measured 2026-09-19).
            placeholders += 1
            continue
        assignments.append(HouseAssignment(code, child.tag, child.get("rank") or None, child.get("leadership") or None))
    return tuple(assignments), placeholders


def _read_house_member(element: Element, index: int) -> HouseMember:
    label = f"MemberData member {index}"
    state_district = _required(element, "statedistrict", label)
    info = single_child(element, "member-info", error_type=CommitteeRosterError, label=label)
    if info is None:
        raise CommitteeRosterError(f"{label} is missing <member-info>")
    bioguide = _text(info, "bioguideID", label)
    fields = {name: _text(info, name, label) for name in _HOUSE_INFO_FIELDS}
    state = single_child(info, "state", error_type=CommitteeRosterError, label=label)
    elected = single_child(info, "elected-date", error_type=CommitteeRosterError, label=label)
    sworn = single_child(info, "sworn-date", error_type=CommitteeRosterError, label=label)
    assignments, placeholders = _read_house_assignments(
        single_child(element, "committee-assignments", error_type=CommitteeRosterError, label=label), label
    )
    if bioguide is None and assignments:
        raise CommitteeRosterError(f"{label} is a vacancy that still lists committee assignments")
    return HouseMember(
        state_district=state_district,
        bioguide_id=bioguide,
        state_code=state.get("postal-code") if state is not None else None,
        state_name=_text(state, "state-fullname", label) if state is not None else None,
        fields=MappingProxyType(fields),
        elected_date=elected.get("date") if elected is not None else None,
        sworn_date=sworn.get("date") if sworn is not None else None,
        assignments=assignments,
        placeholder_assignments=placeholders,
    )


def _ratio(element: Element, label: str) -> tuple[str | None, str | None]:
    ratio = single_child(element, "ratio", error_type=CommitteeRosterError, label=label)
    if ratio is None:
        return None, None
    return _text(ratio, "majority", label), _text(ratio, "minority", label)


def _read_house_committee(element: Element, index: int) -> HouseCommittee:
    label = f"MemberData committees entry {index}"
    code = element.get("comcode")
    if not code:
        raise CommitteeRosterError(f"{label} is missing comcode")
    majority, minority = _ratio(element, label)
    subcommittees: list[HouseSubcommittee] = []
    for child in element.findall("subcommittee"):
        subcode = child.get("subcomcode")
        if not subcode:
            raise CommitteeRosterError(f"{label} has a subcommittee without subcomcode")
        sub_majority, sub_minority = _ratio(child, label)
        subcommittees.append(
            HouseSubcommittee(
                subcode,
                _required(child, "subcommittee-fullname", label),
                sub_majority,
                sub_minority,
                MappingProxyType(dict(child.attrib)),
            )
        )
    return HouseCommittee(
        code=code,
        name=_required(element, "committee-fullname", label),
        type=element.get("type"),
        majority=majority,
        minority=minority,
        subcommittees=tuple(subcommittees),
        attributes=MappingProxyType(dict(element.attrib)),
    )


def parse_house_member_data(body: bytes, *, congress: int, session: int | None = None) -> HouseMemberData:
    """Read the Clerk's ``MemberData.xml`` whole, proving its stated Congress (and session) first.

    A file with zero ``<member>`` elements refuses: the House has 435 voting
    seats and the file lists every seat, filled or vacant, so an empty
    roster is a bad file rather than a fact about the House.
    """
    label = "MemberData"
    root = parse_xml(body, max_bytes=len(body), error_type=CommitteeRosterError, label=label)
    if root.tag != "MemberData":
        raise CommitteeRosterError(f"{label} root must be <MemberData>, got <{root.tag}>")
    title = single_child(root, "title-info", error_type=CommitteeRosterError, label=label)
    if title is None:
        raise CommitteeRosterError(f"{label} is missing <title-info>")
    stated_congress = _int(_required(title, "congress-num", label), label, "congress-num")
    stated_session_text = _text(title, "session", label)
    stated_session = _int(stated_session_text, label, "session") if stated_session_text is not None else None
    if stated_congress != congress or (session is not None and stated_session != session):
        raise CommitteeRosterIdentityError(requested=(congress, session), stated=(stated_congress, stated_session))
    members_element = single_child(root, "members", error_type=CommitteeRosterError, label=label)
    if members_element is None:
        raise CommitteeRosterError(f"{label} is missing <members>")
    members = tuple(_read_house_member(el, i) for i, el in enumerate(members_element.findall("member")))
    if not members:
        raise CommitteeRosterError(f"{label} lists no members")
    committees_element = single_child(root, "committees", error_type=CommitteeRosterError, label=label)
    committees = tuple(
        _read_house_committee(el, i)
        for i, el in enumerate(committees_element.findall("committee") if committees_element is not None else ())
    )
    names: dict[str, str] = {}
    parents: dict[str, str] = {}
    for committee in committees:
        names[committee.code] = committee.name
        for sub in committee.subcommittees:
            names[sub.code] = sub.name
            parents[sub.code] = committee.code
    basis = ("congress:native",) + (("session:native",) if session is not None else ())
    return HouseMemberData(
        congress=stated_congress,
        session=stated_session,
        congress_text=_text(title, "congress-text", label),
        publish_date=root.get("publish-date"),
        majority=_text(title, "majority", label),
        minority=_text(title, "minority", label),
        clerk=_text(title, "clerk", label),
        members=members,
        committees=committees,
        committee_names=MappingProxyType(names),
        parent_codes=MappingProxyType(parents),
        identity_basis=basis,
    )


def _read_senator(element: Element, index: int) -> Senator:
    label = f"cvc senator {index}"
    lis = element.get("lis_member_id")
    if not lis:
        raise CommitteeRosterError(f"{label} is missing lis_member_id")
    bioguide = _text(element, "bioguideId", label)
    if bioguide is None:
        raise CommitteeRosterError(f"{label} is missing <bioguideId>")
    name = single_child(element, "name", error_type=CommitteeRosterError, label=label)
    committees_element = single_child(element, "committees", error_type=CommitteeRosterError, label=label)
    committees: list[SenateCommitteeAssignment] = []
    for child in committees_element if committees_element is not None else ():
        if child.tag != "committee":
            raise CommitteeRosterError(f"{label} committees carries an unknown <{child.tag}>")
        code = child.get("code")
        committee_name = (child.text or "").strip()
        if not code or not committee_name:
            raise CommitteeRosterError(f"{label} has a committee without a code or a name")
        committees.append(SenateCommitteeAssignment(code, committee_name, child.get("position") or None))
    return Senator(
        lis_id=lis,
        bioguide_id=bioguide,
        prefix=_text(name, "prefix", label) if name is not None else None,
        first=_text(name, "first", label) if name is not None else None,
        last=_text(name, "last", label) if name is not None else None,
        suffix=_text(name, "suffix", label) if name is not None else None,
        party=_text(element, "party", label),
        state=_text(element, "state", label),
        home_town=_text(element, "homeTown", label),
        state_rank=_text(element, "stateRank", label),
        office=_text(element, "office", label),
        leadership_position=_text(element, "leadership_position", label),
        committees=tuple(committees),
    )


def parse_senate_cvc(body: bytes) -> SenateCvc:
    """Read ``cvc_member_data.xml`` whole. It states an update date, never a Congress.

    Zero senators refuses; a repeated LIS id or bioguide refuses too, because
    the file promises one seat per senator and a duplicate would give one
    person two assignment rows under one key.
    """
    label = "cvc_member_data"
    root = parse_xml(body, max_bytes=len(body), error_type=CommitteeRosterError, label=label)
    if root.tag != "senators":
        raise CommitteeRosterError(f"{label} root must be <senators>, got <{root.tag}>")
    update = single_child(root, "lastUpdate", error_type=CommitteeRosterError, label=label)
    senators = tuple(_read_senator(el, i) for i, el in enumerate(root.findall("senator")))
    if not senators:
        raise CommitteeRosterError(f"{label} lists no senators")
    seen_lis: set[str] = set()
    seen_bioguide: set[str] = set()
    for senator in senators:
        if senator.lis_id in seen_lis or senator.bioguide_id in seen_bioguide:
            raise CommitteeRosterError(f"{label} repeats senator {senator.lis_id} / {senator.bioguide_id}")
        seen_lis.add(senator.lis_id)
        seen_bioguide.add(senator.bioguide_id)
    return SenateCvc(
        last_update_date=_text(update, "date", label) if update is not None else None,
        last_update_time=_text(update, "time", label) if update is not None else None,
        senators=senators,
    )


@dataclass(frozen=True, slots=True)
class CommitteeRosterBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_ROSTER_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class HouseRosterAcquisition:
    roster: HouseMemberData
    capture: CapturedBodyResponse
    request_count: int
    budget: CommitteeRosterBudget


@dataclass(frozen=True, slots=True)
class SenateRosterAcquisition:
    roster: SenateCvc
    capture: CapturedBodyResponse
    request_count: int
    budget: CommitteeRosterBudget


class CommitteeRosterAcquirer(SourceAcquirer):
    """Keyless capture of either chamber's current roster file, one request each.

    Both hosts are keyless (data map Table C); ``named_challenge`` recasts a
    401/403 as ``CommitteeRosterRefusedError`` the way the votes and
    legislators acquirers do for this package's other keyless families.
    """

    def __init__(
        self,
        *,
        budget: CommitteeRosterBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, CommitteeRosterBudget):
            raise TypeError("budget must be a CommitteeRosterBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-committee-rosters/1.0",
            label="House Clerk / Senate committee roster",
            error_type=CommitteeRosterError,
            context_key="committee_roster_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> CommitteeRosterBudget:
        return self._budget

    def acquire_house(
        self, *, congress: int, session: int | None = None, max_bytes: int | None = None
    ) -> HouseRosterAcquisition:
        """Capture ``MemberData.xml`` and prove its stated Congress (and session) is the one requested."""
        url = HOUSE_MEMBER_DATA_URL
        with named_challenge(url, error_type=CommitteeRosterRefusedError, context_key=self.context_key):
            roster, capture = self.capture_validated(
                url,
                media_types=MEDIA_TYPES,
                parse=lambda response, _limit: parse_house_member_data(
                    response.body, congress=congress, session=session
                ),
                max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes),
                unavailable=CommitteeRosterUnavailableError,
                context={"operation": "house-member-data", "congress": congress, "session": session, "url": url},
            )
        return HouseRosterAcquisition(roster, capture, self.request_count, self.budget)

    def acquire_senate(self, *, max_bytes: int | None = None) -> SenateRosterAcquisition:
        """Capture ``cvc_member_data.xml``. The file states no Congress, so none can be proved here."""
        url = SENATE_CVC_URL
        with named_challenge(url, error_type=CommitteeRosterRefusedError, context_key=self.context_key):
            roster, capture = self.capture_validated(
                url,
                media_types=MEDIA_TYPES,
                parse=lambda response, _limit: parse_senate_cvc(response.body),
                max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes),
                unavailable=CommitteeRosterUnavailableError,
                context={"operation": "senate-cvc", "url": url},
            )
        return SenateRosterAcquisition(roster, capture, self.request_count, self.budget)


__all__ = [
    "DEFAULT_MAX_HOUSE_BYTES",
    "DEFAULT_MAX_SENATE_BYTES",
    "HOUSE_MEMBER_DATA_URL",
    "MAX_ROSTER_BYTES",
    "MEDIA_TYPES",
    "SENATE_CVC_URL",
    "CommitteeRosterAcquirer",
    "CommitteeRosterBudget",
    "CommitteeRosterError",
    "CommitteeRosterIdentityError",
    "CommitteeRosterRefusedError",
    "CommitteeRosterUnavailableError",
    "HouseAssignment",
    "HouseCommittee",
    "HouseMember",
    "HouseMemberData",
    "HouseRosterAcquisition",
    "HouseSubcommittee",
    "SenateCommitteeAssignment",
    "SenateCvc",
    "SenateRosterAcquisition",
    "Senator",
    "house_system_code",
    "parse_house_member_data",
    "parse_senate_cvc",
    "senate_system_code",
]
