"""House Clerk and Senate LIS roll-call vote XML: the tally source `roll_call_votes` and `member_votes` need.

Congress.gov's ``bill/{c}/{type}/{n}/actions`` route attaches a
``recordedVotes`` reference to every voted action -- six sealed fields
(``chamber``, ``congress``, ``date``, ``rollNumber``, ``sessionNumber``,
``url``), measured 58/58 present across two hosts
(``docs/research/billtrax-raw-data-2026-09-19.md`` §5) -- and the House
``house-vote/{c}/{session}/{roll}/members`` route indexes a vote by bill, but
**neither carries the tally or the roster**: both are the index, the two
files this module reads are the tally source
(``docs/sources/congress-votes.md``, "Decision"). BillTrax's
``sync-roll-call-votes.ts``/``roll-call-votes.ts`` stored only
``question``, ``result``, ``yea``/``nay``/``present``/``not_voting``,
``vote_date`` and ``source_url``; its ``upsertMemberVote`` was written but
never called, so no member-level vote ever reached its database. This module
keeps every field either publisher XML states.

Both hosts are keyless (``docs/research/legislative-data-map-2026-09-18.md``
Table C, ``clerk-vote``/``senate-vote``; the sidecar JSON's ``samples``
section pins the measured shape and digest). The Clerk file declares an
external DOCTYPE (``-//US Congress//DTDs/vote v1.0...``);
``reading/xml.py::parse_xml(allow_external_doctype=True)`` tolerates it
without resolving it, the same way ``tools/analysis/legislative_data_map.py``
did to measure it.

**Two identity shapes, one crosswalk.** The Clerk file states its own
congress/session/roll number (``vote-metadata/{congress,session,rollcall-num}``);
the Clerk's URL states only a calendar year and the roll number
(``evs/{year}/roll{N}.xml``), so building or parsing that URL needs the
year<->(congress, session) rule documented on ``_clerk_year`` below. The
Senate file also states its own identity (``congress``, ``session``,
``vote_number``), and its URL states congress, session and the roll number
directly (``vote{congress}{session}/vote_{congress}_{session}_{roll}.xml``).
Senate votes key members on ``lis_member_id``, not bioguide; the only
publisher crosswalk from LIS to bioguide already in this package is
``sources/legislators.py::LegislatorsFile.by_lis`` (measured absent for
roughly 4 of 99 voters on any one vote, since a member who has just left
carries no current-roster row -- a real absence, not a malformed one), so
``parse_senate_vote`` takes it as an optional parameter rather than building
a second crosswalk.

**Identity proof.** ``parse_clerk_vote``/``parse_senate_vote`` both take the
``VoteLocator`` the caller requested and check the file's own stated
congress/session/roll number against it before returning anything; a
mismatch raises ``VoteIdentityError``, a family member of ``VoteSourceError``
like every other refusal here, so the acquirer's ``capture_validated``
attaches the fetched bytes as evidence to it the same way it does for a
malformed body -- proving the fetched file is the one requested, not just
that the URL was built correctly.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from xml.etree.ElementTree import Element

from spicy_docs.interpretation.vote_matching import VOTE_CHAMBERS, VoteKey, VoteMatchError
from spicy_docs.reading.rss import child_text, single_child
from spicy_docs.reading.xml import parse_xml
from spicy_docs.sources.legislators import LegislatorsFile
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    named_challenge,
    utc_now,
)

if TYPE_CHECKING:
    from datetime import datetime

    import httpx

type Chamber = Literal["house", "senate"]
type Publisher = Literal["clerk", "senate-lis"]
type NormalizedVote = Literal["yea", "nay", "present", "not_voting"]

MEDIA_TYPES = ("text/xml", "application/xml")
# Measured 2026-09-18/19: Clerk roll 240 is 82,515 B, the Senate vote is
# 28,670 B (docs/research/legislative-data-map-2026-09-18.json samples).
# DEFAULT_MAX_BYTES keeps roughly 6x headroom over the larger measured file.
DEFAULT_MAX_BYTES = 512 * 1024
MAX_VOTE_BYTES = 4 * 1024 * 1024

CLERK_URL_RE = re.compile(r"^https://clerk\.house\.gov/evs/(?P<year>\d{4})/roll(?P<roll>\d+)\.xml$")
SENATE_URL_RE = re.compile(
    r"^https://www\.senate\.gov/legislative/LIS/roll_call_votes/"
    r"vote(?P<congress>\d{3})(?P<session>\d)/vote_(?P<congress2>\d{3})_(?P<session2>\d)_(?P<roll>\d+)\.xml$"
)

# Session 1 of Congress N convenes January 3 of an odd calendar year; the 20th
# Amendment fixed this from the 74th Congress (1935) onward. The Clerk's own
# EVS URL carries only that calendar year and the roll number -- no congress
# or session -- so building or parsing one needs this rule; the Clerk's
# archive begins in 1990 (101st Congress), well inside the fixed range
# (docs/research/legislative-data-map-2026-09-18.md: "the Clerk XML ...
# reaches 1990"). Session 2 falls in the following (even) calendar year.
_FIRST_SESSION_YEAR = 1789
_EARLIEST_FIXED_CALENDAR_CONGRESS = 74

# Measured 2026-09-19: senate.gov/legislative/LIS/roll_call_lists/vote_menu_101_1.xml
# serves a real 149,123-byte listing and vote1011/vote_101_1_00001.xml answers
# 200; vote_menu_100_1.xml and vote_menu_099_1.xml (and 089, 080) each 302 to
# roll-call-vote-not-available.htm. The Senate LIS archive's floor is the
# 101st Congress -- the same floor the Clerk's EVS archive measures -- so
# every real congress this route can serve is already three digits and
# ``senate_url``'s zero-padding never needs a two-digit case.
_EARLIEST_SENATE_CONGRESS = 101

_CLERK_COUNT_FIELDS = ("yea-total", "nay-total", "present-total", "not-voting-total")
_SENATE_COUNT_FIELDS = ("yeas", "nays", "present", "absent")

# The Clerk spells Yea/Nay on a YEA-AND-NAY vote and Aye/No on some
# RECORDED VOTEs; both fixtures pinned here only ever carry Yea/Nay/Not
# Voting (measured), but the DTD's wider vocabulary is accepted so a future
# RECORDED VOTE fixture does not need a second normalization table.
_VOTE_NORMALIZATION: Mapping[str, NormalizedVote] = MappingProxyType(
    {
        "yea": "yea",
        "aye": "yea",
        "nay": "nay",
        "no": "nay",
        "present": "present",
        "not voting": "not_voting",
    }
)


class VoteSourceError(ValueError):
    """The response cannot establish a House Clerk or Senate LIS roll-call vote."""


class VoteUnavailableError(VoteSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"roll-call vote source answered HTTP {capture.status_code}")
        self.capture = capture


class VoteRefusedError(VoteSourceError):
    """A keyless route answered 401/403; there is no credential here to reject.

    Neither clerk.house.gov nor senate.gov names a credential, but either can
    still bot-wall a request. ``named_challenge`` recasts that refusal into
    this error so it is catchable as a ``VoteSourceError``, its body retained
    as evidence on ``refused_response``, the way ``LegislatorsRefusedError``
    and ``PressReleaseFeedRefusedError`` already do for this package's other
    keyless families.
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"roll-call vote source refused access to {url}; no credential exists to reject")
        self.url = url


class VoteIdentityError(VoteSourceError):
    """The file's own stated congress/session/roll number does not match the locator that requested it."""

    def __init__(self, locator: VoteLocator, *, parsed: tuple[int, int, int]) -> None:
        super().__init__(
            f"{locator.chamber} roll-call vote fetched for congress={locator.congress} session={locator.session} "
            f"roll={locator.roll_number} states a different identity: congress={parsed[0]} session={parsed[1]} "
            f"roll={parsed[2]}"
        )
        self.locator = locator
        self.parsed = parsed


def _as_vote_key(chamber: str, congress: int, session: int, roll_number: int) -> VoteKey:
    """Build a ``vote_matching.VoteKey``, translating its shape rule into this module's error family."""
    try:
        return VoteKey(congress=congress, chamber=chamber, session=session, roll_number=roll_number)
    except VoteMatchError as error:
        raise VoteSourceError(str(error)) from error


@dataclass(frozen=True, slots=True)
class VoteLocator:
    """One roll call's publisher identity: which chamber, which Congress, which session, which roll number.

    ``url()`` dispatches to the right publisher's URL grammar;
    ``locator_from_recorded_vote_url`` parses either grammar back to a
    locator. Shape validation is delegated to ``vote_matching.VoteKey``
    (``as_vote_key``), the type a downstream matcher already uses, rather
    than restating "chamber is house or senate, the rest are non-negative
    integers" a second time.
    """

    chamber: Chamber
    congress: int
    session: int
    roll_number: int

    def __post_init__(self) -> None:
        if self.chamber not in VOTE_CHAMBERS:
            raise VoteSourceError("chamber must be 'house' or 'senate'")
        _as_vote_key(self.chamber, self.congress, self.session, self.roll_number)

    def as_vote_key(self) -> VoteKey:
        return _as_vote_key(self.chamber, self.congress, self.session, self.roll_number)

    def url(self) -> str:
        return clerk_url(self) if self.chamber == "house" else senate_url(self)


def _clerk_year(congress: int, session: int) -> int:
    if congress < _EARLIEST_FIXED_CALENDAR_CONGRESS:
        raise VoteSourceError(
            f"congress {congress} predates the fixed session calendar (74th Congress, 1935); "
            "the Clerk's EVS archive never reaches this far (measured floor: 1990, the 101st Congress)"
        )
    if session not in (1, 2):
        raise VoteSourceError("session must be 1 or 2 to build a Clerk EVS url")
    return _FIRST_SESSION_YEAR + 2 * (congress - 1) + (session - 1)


def clerk_url(locator: VoteLocator) -> str:
    """Build the Clerk EVS url; see the module docstring for the year<->(congress, session) rule.

    The roll number is zero-padded to three digits (``roll050.xml``,
    ``roll096.xml`` -- measured in ``billtrax-raw-data-2026-09-19.json``'s
    real ``recordedVotes`` urls); a roll past 999 still prints in full since
    ``:03d`` is a minimum width, not a truncation.
    """
    if locator.chamber != "house":
        raise VoteSourceError("clerk_url requires a 'house' locator")
    year = _clerk_year(locator.congress, locator.session)
    return f"https://clerk.house.gov/evs/{year}/roll{locator.roll_number:03d}.xml"


def senate_url(locator: VoteLocator) -> str:
    """Build the Senate LIS url; congress, session and roll number all appear in it directly.

    The congress is zero-padded to three digits, matching ``SENATE_URL_RE``;
    every real congress this route can serve is already three digits (the
    LIS archive's own floor is the 101st Congress -- see
    ``_EARLIEST_SENATE_CONGRESS`` above), so this raises rather than build an
    unmeasured two-digit-congress url no fixture or probe has ever confirmed.
    """
    if locator.chamber != "senate":
        raise VoteSourceError("senate_url requires a 'senate' locator")
    if locator.congress < _EARLIEST_SENATE_CONGRESS:
        raise VoteSourceError(
            f"congress {locator.congress} predates the Senate LIS archive (measured floor: the 101st Congress)"
        )
    congress = f"{locator.congress:03d}"
    return (
        "https://www.senate.gov/legislative/LIS/roll_call_votes/"
        f"vote{congress}{locator.session}/vote_{congress}_{locator.session}_{locator.roll_number:05d}.xml"
    )


def locator_from_recorded_vote_url(url: str) -> VoteLocator:
    """Parse a `recordedVotes[].url` (billtrax-raw-data-2026-09-19.md §5) back to a locator.

    Only the two measured shapes resolve: ``clerk.house.gov/evs`` and
    ``senate.gov .../roll_call_votes``. The Senate shape states congress and
    session twice (the folder and the filename); a disagreement between them
    refuses rather than silently picking one. The Clerk shape states neither,
    so the year is inverted through the same fixed-calendar rule
    ``clerk_url`` uses to build one.
    """
    senate_match = SENATE_URL_RE.match(url)
    if senate_match:
        congress, session = int(senate_match["congress"]), int(senate_match["session"])
        if (congress, session) != (int(senate_match["congress2"]), int(senate_match["session2"])):
            raise VoteSourceError(f"senate roll-call vote url names inconsistent congress/session: {url!r}")
        if congress < _EARLIEST_SENATE_CONGRESS:
            raise VoteSourceError(f"senate roll-call vote url predates the LIS archive: {url!r}")
        return VoteLocator("senate", congress, session, int(senate_match["roll"]))
    clerk_match = CLERK_URL_RE.match(url)
    if clerk_match:
        year = int(clerk_match["year"])
        session = 1 if year % 2 == 1 else 2
        congress = (year - _FIRST_SESSION_YEAR) // 2 + 1 if session == 1 else (year - 1 - _FIRST_SESSION_YEAR) // 2 + 1
        if congress < _EARLIEST_FIXED_CALENDAR_CONGRESS:
            raise VoteSourceError(f"clerk roll-call vote url predates the fixed session calendar: {url!r}")
        return VoteLocator("house", congress, session, int(clerk_match["roll"]))
    raise VoteSourceError(f"{url!r} is not a recognized Clerk or Senate roll-call vote url")


def normalize_vote(value: str) -> NormalizedVote:
    """Map a publisher-spelled vote value to the shared vocabulary; the raw spelling is kept beside it on ``MemberVote``."""
    key = " ".join(value.split()).casefold()
    try:
        return _VOTE_NORMALIZATION[key]
    except KeyError:
        raise VoteSourceError(f"unrecognized roll-call vote value: {value!r}") from None


@dataclass(frozen=True, slots=True)
class PartyTotal:
    """One Clerk ``totals-by-party`` row: the publisher's own count names, not a normalized tally."""

    party: str
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class TieBreaker:
    """The Senate's ``tie_breaker`` block; both fields are ``None`` when the vote was not tied."""

    by_whom: str | None
    tie_breaker_vote: str | None


@dataclass(frozen=True, slots=True)
class VoteDocument:
    """The Senate's ``document`` block: the bill, resolution or nomination the vote was taken on.

    This is the publisher's own statement of what the vote was on, kept
    verbatim; matching it to a Congress.gov bill or nomination record is
    ``vote_matching``'s job (the data map's ``senate-vote->document`` edge),
    not this reader's.
    """

    congress: int | None
    type: str | None
    number: str | None
    name: str | None
    title: str | None
    short_title: str | None


@dataclass(frozen=True, slots=True)
class VoteAmendment:
    """The Senate's ``amendment`` block; every field is ``None`` when the vote carried no amendment."""

    number: str | None
    to_amendment_number: str | None
    to_amendment_to_amendment_number: str | None
    to_document_number: str | None
    to_document_short_title: str | None
    purpose: str | None


@dataclass(frozen=True, slots=True)
class MemberVote:
    """One member's recorded vote, publisher-spelled beside the crosswalked and normalized values.

    ``bioguide_id``/``lis_id`` are ``None`` when that publisher does not
    carry the id or (Senate only) the crosswalk could not resolve it -- a
    real absence, not a malformed record (measured: roughly 4 of 99 Senate
    voters on any one vote, a member who has just left the current roster).
    ``sort_field``/``unaccented_name``/``role`` are Clerk-only;
    ``member_full``/``first_name``/``last_name`` are Senate-only.
    """

    bioguide_id: str | None
    lis_id: str | None
    name: str
    party: str
    state: str
    vote: str
    vote_normalized: NormalizedVote

    sort_field: str | None = None
    unaccented_name: str | None = None
    role: str | None = None

    member_full: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True, slots=True)
class RollCallVote:
    """One roll call, shared fields first, then each publisher's own extra fields kept beside them.

    ``tallies`` keeps the publisher's own count names (Clerk:
    ``yea-total``/``nay-total``/``present-total``/``not-voting-total`` from
    ``totals-by-vote``; Senate: ``yeas``/``nays``/``present``/``absent`` from
    ``count``) rather than a normalized ``{yea, nay, ...}`` shape, so nothing
    about which bucket a publisher meant is lost before a transform decides
    how to fold them. ``party_totals`` (Clerk only) is the "totals by party"
    breakdown the totals-by-vote row summarizes.
    """

    publisher: Publisher
    chamber: Chamber
    congress: int
    session: int
    roll_number: int
    date: str | None
    question: str | None
    result: str | None
    tallies: Mapping[str, int]
    source_url: str
    member_votes: tuple[MemberVote, ...]

    # Clerk-only (None/() for a Senate record).
    majority: str | None = None
    legis_num: str | None = None
    vote_type: str | None = None
    vote_desc: str | None = None
    action_time: str | None = None
    action_time_etz: str | None = None
    chamber_raw: str | None = None
    session_raw: str | None = None
    party_totals: tuple[PartyTotal, ...] = ()

    # Senate-only (None for a Clerk record).
    congress_year: int | None = None
    modify_date: str | None = None
    vote_question_text: str | None = None
    vote_document_text: str | None = None
    vote_result_text: str | None = None
    vote_title: str | None = None
    majority_requirement: str | None = None
    tie_breaker: TieBreaker | None = None
    document: VoteDocument | None = None
    amendment: VoteAmendment | None = None

    def vote_key(self) -> VoteKey:
        return _as_vote_key(self.chamber, self.congress, self.session, self.roll_number)


def _required_int(value: str | None, label: str, field: str) -> int:
    if value is None or not value.strip().lstrip("-").isdigit():
        raise VoteSourceError(f"{label} <{field}> must be an integer: {value!r}")
    return int(value)


def _optional_int(value: str | None, label: str, field: str) -> int:
    """A missing or blank count element means zero (measured: the Senate's `<present/>` when no one did)."""
    if value is None:
        return 0
    if not value.strip().lstrip("-").isdigit():
        raise VoteSourceError(f"{label} <{field}> must be an integer: {value!r}")
    return int(value)


def _parse_ordinal_session(value: str | None, label: str) -> int:
    if value is None:
        raise VoteSourceError(f"{label} <session> is not an ordinal like '1st': {value!r}")
    match = re.fullmatch(r"(\d+)(st|nd|rd|th)", value.strip())
    if not match:
        raise VoteSourceError(f"{label} <session> is not an ordinal like '1st': {value!r}")
    return int(match.group(1))


def _read_counts(element: Element, fields: tuple[str, ...], label: str) -> Mapping[str, int]:
    return MappingProxyType(
        {
            field: _required_int(child_text(element, field, error_type=VoteSourceError, label=label), label, field)
            for field in fields
        }
    )


def _check_identity(locator: VoteLocator, *, congress: int, session: int, roll_number: int) -> None:
    if (congress, session, roll_number) != (locator.congress, locator.session, locator.roll_number):
        raise VoteIdentityError(locator, parsed=(congress, session, roll_number))


def _read_party_total(element: Element, label: str) -> PartyTotal:
    party = child_text(element, "party", error_type=VoteSourceError, label=label)
    if party is None:
        raise VoteSourceError(f"{label} totals-by-party is missing <party>")
    return PartyTotal(party=party, counts=_read_counts(element, _CLERK_COUNT_FIELDS, label))


def _read_clerk_member(element: Element, label: str) -> MemberVote:
    legislator = single_child(element, "legislator", error_type=VoteSourceError, label=label)
    vote_element = single_child(element, "vote", error_type=VoteSourceError, label=label)
    if legislator is None or vote_element is None:
        raise VoteSourceError(f"{label} recorded-vote requires <legislator> and <vote>")
    bioguide_id, party, state = legislator.get("name-id"), legislator.get("party"), legislator.get("state")
    name = (legislator.text or "").strip()
    if not bioguide_id or not party or not state or not name:
        raise VoteSourceError(f"{label} recorded-vote legislator is missing name-id, party, state or its name text")
    vote_text = (vote_element.text or "").strip()
    if not vote_text:
        raise VoteSourceError(f"{label} recorded-vote <vote> is empty")
    return MemberVote(
        bioguide_id=bioguide_id,
        lis_id=None,
        name=name,
        party=party,
        state=state,
        vote=vote_text,
        vote_normalized=normalize_vote(vote_text),
        sort_field=legislator.get("sort-field"),
        unaccented_name=legislator.get("unaccented-name"),
        role=legislator.get("role"),
    )


def parse_clerk_vote(body: bytes, locator: VoteLocator) -> RollCallVote:
    """Read one House Clerk EVS roll-call file (``<rollcall-vote>``) whole; every field it states is kept.

    Byte-bounding happens at the acquirer (``capture_validated``), the same
    way ``tools/analysis/legislative_data_map.py``'s own probe reads this
    file (``parse_xml(body, max_bytes=len(body), ...)``); called directly,
    the caller's own bytes are the bound.
    """
    if locator.chamber != "house":
        raise VoteSourceError("parse_clerk_vote requires a 'house' locator")
    label = "Clerk roll-call vote"
    root = parse_xml(body, max_bytes=len(body), error_type=VoteSourceError, label=label, allow_external_doctype=True)
    if root.tag != "rollcall-vote":
        raise VoteSourceError(f"{label} root must be <rollcall-vote>, got <{root.tag}>")
    metadata = single_child(root, "vote-metadata", error_type=VoteSourceError, label=label)
    data = single_child(root, "vote-data", error_type=VoteSourceError, label=label)
    if metadata is None or data is None:
        raise VoteSourceError(f"{label} requires both <vote-metadata> and <vote-data>")

    def meta(tag: str, *, required: bool = True) -> str | None:
        value = child_text(metadata, tag, error_type=VoteSourceError, label=label)
        if required and value is None:
            raise VoteSourceError(f"{label} vote-metadata is missing <{tag}>")
        return value

    session_raw = meta("session")
    congress = _required_int(meta("congress"), label, "congress")
    session = _parse_ordinal_session(session_raw, label)
    roll_number = _required_int(meta("rollcall-num"), label, "rollcall-num")
    _check_identity(locator, congress=congress, session=session, roll_number=roll_number)

    action_time_element = single_child(metadata, "action-time", error_type=VoteSourceError, label=label)
    action_time = (action_time_element.text or "").strip() or None if action_time_element is not None else None
    action_time_etz = action_time_element.get("time-etz") if action_time_element is not None else None

    totals = single_child(metadata, "vote-totals", error_type=VoteSourceError, label=label)
    if totals is None:
        raise VoteSourceError(f"{label} is missing <vote-totals>")
    party_totals = tuple(_read_party_total(el, label) for el in totals.findall("totals-by-party"))
    totals_by_vote = single_child(totals, "totals-by-vote", error_type=VoteSourceError, label=label)
    if totals_by_vote is None:
        raise VoteSourceError(f"{label} is missing <totals-by-vote>")
    tallies = _read_counts(totals_by_vote, _CLERK_COUNT_FIELDS, label)

    member_votes = tuple(_read_clerk_member(el, label) for el in data.findall("recorded-vote"))
    if not member_votes:
        raise VoteSourceError(
            f"{label} for congress={congress} session={session} roll={roll_number} lists no recorded votes"
        )

    return RollCallVote(
        publisher="clerk",
        chamber="house",
        congress=congress,
        session=session,
        roll_number=roll_number,
        date=meta("action-date", required=False),
        question=meta("vote-question", required=False),
        result=meta("vote-result", required=False),
        tallies=tallies,
        source_url=locator.url(),
        member_votes=member_votes,
        majority=meta("majority", required=False),
        legis_num=meta("legis-num", required=False),
        vote_type=meta("vote-type", required=False),
        vote_desc=meta("vote-desc", required=False),
        action_time=action_time,
        action_time_etz=action_time_etz,
        chamber_raw=meta("chamber", required=False),
        session_raw=session_raw,
        party_totals=party_totals,
    )


def _read_tie_breaker(element: Element, label: str) -> TieBreaker:
    return TieBreaker(
        by_whom=child_text(element, "by_whom", error_type=VoteSourceError, label=label),
        tie_breaker_vote=child_text(element, "tie_breaker_vote", error_type=VoteSourceError, label=label),
    )


def _optional_int_or_none(value: str | None, label: str, field: str) -> int | None:
    """Unlike ``_optional_int`` (counts, where absent means zero), an absent id here just means absent."""
    if value is None:
        return None
    if not value.strip().lstrip("-").isdigit():
        raise VoteSourceError(f"{label} <{field}> must be an integer: {value!r}")
    return int(value)


def _read_document(element: Element, label: str) -> VoteDocument:
    def text(tag: str) -> str | None:
        return child_text(element, tag, error_type=VoteSourceError, label=label)

    return VoteDocument(
        congress=_optional_int_or_none(text("document_congress"), label, "document_congress"),
        type=text("document_type"),
        number=text("document_number"),
        name=text("document_name"),
        title=text("document_title"),
        short_title=text("document_short_title"),
    )


def _read_amendment(element: Element, label: str) -> VoteAmendment:
    def text(tag: str) -> str | None:
        return child_text(element, tag, error_type=VoteSourceError, label=label)

    return VoteAmendment(
        number=text("amendment_number"),
        to_amendment_number=text("amendment_to_amendment_number"),
        to_amendment_to_amendment_number=text("amendment_to_amendment_to_amendment_number"),
        to_document_number=text("amendment_to_document_number"),
        to_document_short_title=text("amendment_to_document_short_title"),
        purpose=text("amendment_purpose"),
    )


def _read_senate_member(element: Element, label: str, crosswalk: LegislatorsFile | None) -> MemberVote:
    def text(tag: str) -> str:
        value = child_text(element, tag, error_type=VoteSourceError, label=label)
        if value is None:
            raise VoteSourceError(f"{label} member is missing <{tag}>")
        return value

    member_full, party, state = text("member_full"), text("party"), text("state")
    vote_cast, lis_id = text("vote_cast"), text("lis_member_id")
    resolved = crosswalk.by_lis.get(lis_id) if crosswalk is not None else None
    return MemberVote(
        bioguide_id=resolved.bioguide if resolved is not None else None,
        lis_id=lis_id,
        name=member_full,
        party=party,
        state=state,
        vote=vote_cast,
        vote_normalized=normalize_vote(vote_cast),
        member_full=member_full,
        first_name=text("first_name"),
        last_name=text("last_name"),
    )


def parse_senate_vote(body: bytes, locator: VoteLocator, crosswalk: LegislatorsFile | None = None) -> RollCallVote:
    """Read one Senate LIS roll-call file (``<roll_call_vote>``) whole; every field it states is kept.

    ``crosswalk``, when given, resolves each member's ``lis_member_id`` to a
    bioguide id through ``LegislatorsFile.by_lis``
    (``sources/legislators.py``); an id the crosswalk does not carry
    resolves to ``bioguide_id=None`` rather than refusing the member, since
    that is a real, measured absence (a senator who has just left the
    current roster), not a malformed record.
    """
    if locator.chamber != "senate":
        raise VoteSourceError("parse_senate_vote requires a 'senate' locator")
    label = "Senate LIS roll-call vote"
    root = parse_xml(body, max_bytes=len(body), error_type=VoteSourceError, label=label)
    if root.tag != "roll_call_vote":
        raise VoteSourceError(f"{label} root must be <roll_call_vote>, got <{root.tag}>")

    def text(tag: str, *, required: bool = True) -> str | None:
        value = child_text(root, tag, error_type=VoteSourceError, label=label)
        if required and value is None:
            raise VoteSourceError(f"{label} is missing <{tag}>")
        return value

    congress = _required_int(text("congress"), label, "congress")
    session = _required_int(text("session"), label, "session")
    roll_number = _required_int(text("vote_number"), label, "vote_number")
    _check_identity(locator, congress=congress, session=session, roll_number=roll_number)

    count = single_child(root, "count", error_type=VoteSourceError, label=label)
    if count is None:
        raise VoteSourceError(f"{label} is missing <count>")
    tallies = MappingProxyType(
        {
            field: _optional_int(child_text(count, field, error_type=VoteSourceError, label=label), label, field)
            for field in _SENATE_COUNT_FIELDS
        }
    )

    tie_element = single_child(root, "tie_breaker", error_type=VoteSourceError, label=label)
    tie_breaker = _read_tie_breaker(tie_element, label) if tie_element is not None else None

    document_element = single_child(root, "document", error_type=VoteSourceError, label=label)
    document = _read_document(document_element, label) if document_element is not None else None

    amendment_element = single_child(root, "amendment", error_type=VoteSourceError, label=label)
    amendment = _read_amendment(amendment_element, label) if amendment_element is not None else None

    members = single_child(root, "members", error_type=VoteSourceError, label=label)
    if members is None:
        raise VoteSourceError(f"{label} is missing <members>")
    member_votes = tuple(_read_senate_member(el, label, crosswalk) for el in members.findall("member"))
    if not member_votes:
        raise VoteSourceError(f"{label} for congress={congress} session={session} roll={roll_number} lists no members")

    return RollCallVote(
        publisher="senate-lis",
        chamber="senate",
        congress=congress,
        session=session,
        roll_number=roll_number,
        date=text("vote_date", required=False),
        question=text("question", required=False),
        result=text("vote_result", required=False),
        tallies=tallies,
        source_url=locator.url(),
        member_votes=member_votes,
        congress_year=_required_int(text("congress_year"), label, "congress_year"),
        modify_date=text("modify_date", required=False),
        vote_question_text=text("vote_question_text", required=False),
        vote_document_text=text("vote_document_text", required=False),
        vote_result_text=text("vote_result_text", required=False),
        vote_title=text("vote_title", required=False),
        majority_requirement=text("majority_requirement", required=False),
        tie_breaker=tie_breaker,
        document=document,
        amendment=amendment,
    )


@dataclass(frozen=True, slots=True)
class VoteBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_VOTE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class VoteAcquisition:
    vote: RollCallVote
    capture: CapturedBodyResponse
    request_count: int
    budget: VoteBudget


class VoteAcquirer(SourceAcquirer):
    """Keyless capture of one roll-call vote from either publisher, sharing one acquirer and one error family.

    ``acquire`` builds the url from the locator and dispatches on
    ``locator.chamber`` to ``parse_clerk_vote`` or ``parse_senate_vote``.
    Both hosts are keyless (data map Table C); ``named_challenge`` recasts a
    401/403 as ``VoteRefusedError`` the way ``LegislatorsRefusedError`` and
    ``PressReleaseFeedRefusedError`` already do for this package's other
    keyless families. The identity check inside each parser raises
    ``VoteIdentityError`` on a mismatch, and ``capture_validated`` attaches
    the fetched bytes to it as evidence like any other failure here.
    """

    def __init__(
        self,
        *,
        budget: VoteBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, VoteBudget):
            raise TypeError("budget must be a VoteBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-congress-votes/1.0",
            label="House Clerk / Senate LIS roll-call vote",
            error_type=VoteSourceError,
            context_key="vote_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> VoteBudget:
        return self._budget

    def acquire(self, locator: VoteLocator, *, crosswalk: LegislatorsFile | None = None) -> VoteAcquisition:
        if not isinstance(locator, VoteLocator):
            raise TypeError("locator must be a VoteLocator")
        url = locator.url()

        def parse(response: CapturedBodyResponse, _allowance: int) -> RollCallVote:
            if locator.chamber == "house":
                return parse_clerk_vote(response.body, locator)
            return parse_senate_vote(response.body, locator, crosswalk)

        with named_challenge(url, error_type=VoteRefusedError, context_key="vote_acquisition"):
            vote, capture = self.capture_validated(
                url,
                media_types=MEDIA_TYPES,
                parse=parse,
                max_bytes=self.budget.max_bytes,
                unavailable=VoteUnavailableError,
                context={"operation": "roll-call-vote", "chamber": locator.chamber, "url": url},
            )
        return VoteAcquisition(vote, capture, self.request_count, self.budget)


__all__ = [
    "CLERK_URL_RE",
    "DEFAULT_MAX_BYTES",
    "MAX_VOTE_BYTES",
    "MEDIA_TYPES",
    "SENATE_URL_RE",
    "MemberVote",
    "PartyTotal",
    "RollCallVote",
    "TieBreaker",
    "VoteAcquirer",
    "VoteAcquisition",
    "VoteAmendment",
    "VoteBudget",
    "VoteDocument",
    "VoteIdentityError",
    "VoteLocator",
    "VoteRefusedError",
    "VoteSourceError",
    "VoteUnavailableError",
    "clerk_url",
    "locator_from_recorded_vote_url",
    "normalize_vote",
    "parse_clerk_vote",
    "parse_senate_vote",
    "senate_url",
]
