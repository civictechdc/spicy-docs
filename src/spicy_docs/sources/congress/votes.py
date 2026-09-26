"""House Clerk and Senate LIS roll-call vote XML: the tally source `roll_call_votes` and `member_votes` need.

Congress.gov's ``recordedVotes`` reference and its ``house-vote`` route are the
index only -- neither carries the tally or the roster -- and BillTrax stored
only summary fields, never a member-level vote. This module reads the two
publisher files that do carry them, keeping every field either publisher XML
states. Both hosts are keyless; the Clerk file declares an external DOCTYPE,
which ``reading/xml.py::parse_xml(allow_external_doctype=True)`` tolerates
without resolving it.

**Two identity shapes, one crosswalk.** The Clerk file states its own
congress/session/roll number, while its URL states only a calendar year and
the roll number, so building or parsing that URL needs the
year<->(congress, session) rule documented on ``_clerk_year`` below. The
Senate file and URL both state their identity. Senate votes key members on
``lis_member_id``, not bioguide; the only LIS-to-bioguide crosswalk already in
this package is ``sources/legislators.py::LegislatorsFile.by_lis`` (measured
absent for roughly 4 of 99 voters on any one vote, since a member who has just
left carries no current-roster row -- a real absence, not a malformed one), so
``parse_senate_vote`` takes it as an optional parameter rather than building a
second crosswalk.

**Identity proof.** ``parse_clerk_vote``/``parse_senate_vote`` both take the
``VoteLocator`` the caller requested and check the file's own stated
congress/session/roll number against it before returning anything; a mismatch
raises ``VoteIdentityError``, a family member of ``VoteSourceError`` like
every other refusal here, so the acquirer attaches the fetched bytes as
evidence to it the same way it does for a malformed body.

**The Senate roll-call index.** Congress.gov has no Senate equivalent of
``house-vote``: the only Senate index at all is the LIS menu file itself, one
row per vote for the session, in the publisher's own newest-vote-first order.
``parse_senate_vote_menu``/``VoteAcquirer.list_senate_votes`` read it the same
way as the vote files above: the file's own ``congress``/``session`` proved
against what was requested (``VoteMenuIdentityError`` on a mismatch) and a
well-formed file with zero listed votes refused rather than returned as an
empty success. ``locator_from_menu_entry`` turns one row into the
``VoteLocator`` that resolves its full tally and roster.

**The House roll-call index.** Congress.gov's ``house-vote`` route answers an
empty success before the 115th Congress, so the House's own index is the
Clerk's EVS year page and the hundred-row pages it links.
``VoteAcquirer.list_house_votes`` reads every page, proves each page's stated
congress/session against the request (``VoteMenuIdentityError``) and refuses a
session whose rolls do not run 1..N without a gap.

**The vote day.** Each publisher prints the day it voted in its own spelling
(Clerk ``8-Sep-2025``; Senate ``January 9, 2025,  02:54 PM``), both in Eastern
local time. ``vote_day`` reads either into an ISO date and is the one owner of
that rule; ``RollCallVote.day`` exposes it, and a record whose printed date it
cannot read refuses at parse time rather than publishing a day it guessed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from xml.etree.ElementTree import Element

from spicy_docs.interpretation.vote_matching import VOTE_CHAMBERS, VoteKey, VoteMatchError
from spicy_docs.reading.markup import decode_html_page, feed_html, joined_text
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
# Measured 2026-09-19: vote_menu_119_1.xml (the 119th Congress, 1st session,
# 659 votes so far) is 419,112 B -- a session-length list, not one vote, so it
# needs its own headroom rather than sharing DEFAULT_MAX_BYTES.
DEFAULT_MENU_MAX_BYTES = 1024 * 1024

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
# The menu's own <vote_tally> states only yeas/nays (measured 2026-09-19,
# 659/659 entries of vote_menu_119_1.xml) -- present/absent live only on the
# per-vote file this menu indexes, not the index itself.
_SENATE_MENU_TALLY_FIELDS = ("yeas", "nays")

# The Clerk's own session index: ``evs/{year}/index.asp`` links hundred-row pages
# (``ROLL_000.asp`` .. ``ROLL_1100.asp``), one six-cell row per roll call.
# Measured 2026-09-26 over every page of 2003-2024 (108th-118th Congresses, 201
# requests): all 14,774 rows have six cells, every page is ASCII, and every
# session's rolls run 1..N without a gap (receipt:
# ~/Work/corpora/fork-execution-2026-09-21/votes-backfill-2026-09-26/survey/).
CLERK_INDEX_MEDIA_TYPES = ("text/html",)
_CLERK_INDEX_PAGE_RE = re.compile(r"ROLL_\d{3,}\.asp")
_CLERK_INDEX_VOTE_RE = re.compile(
    r"https?://clerk\.house\.gov/cgi-bin/vote\.asp\?year=(?P<year>\d{4})&rollnumber=(?P<roll>\d+)"
)
_CLERK_INDEX_HEADING_RE = re.compile(
    r"(?P<congress>\d+)(?:st|nd|rd|th) Congress - (?P<session>\d)(?:st|nd|rd|th) Session \((?P<year>\d{4})\)"
)
_CLERK_INDEX_CELLS = 6
_CLERK_INDEX_CELL_BOUND = 4096

# The Clerk spells Yea/Nay on a YEA-AND-NAY vote and Aye/No on some
# RECORDED VOTEs; both fixtures pinned here only ever carry Yea/Nay/Not
# Voting (measured), but the DTD's wider vocabulary is accepted so a future
# RECORDED VOTE fixture does not need a second normalization table.
#
# The Senate's older and rarer spellings fold where its own ``<count>`` block
# counts them (measured 2026-09-26 over 72 LIS files of the 108th-118th: every
# vote Voteview codes Present, and the three impeachment verdicts): an
# impeachment verdict's Guilty/Not Guilty in ``yeas``/``nays`` (116-2-33 and
# -34, 117-1-59), and a present senator's live pair in ``present`` (108-2-213).
_VOTE_NORMALIZATION: Mapping[str, NormalizedVote] = MappingProxyType(
    {
        "yea": "yea",
        "aye": "yea",
        "guilty": "yea",
        "nay": "nay",
        "no": "nay",
        "not guilty": "nay",
        "present": "present",
        "present, giving live pair": "present",
        "not voting": "not_voting",
    }
)


# Each chamber's own spelling of the day it voted: the Clerk's ``action-date``
# (``8-Sep-2025``) and the Senate's ``vote_date`` (``January 9, 2025,  02:54 PM``,
# a doubled space before the time), measured unchanged back to each archive's
# floor (docs/sources/congress-votes.md, "Vote day"). The Senate's clock is
# matched only so a malformed one refuses; the day is the printed (Eastern)
# day, never converted through UTC. English month names are looked up here
# rather than read by ``strptime``'s ``%b``/``%B``, which follow the process's
# ``LC_TIME`` locale (the reason ``bulk_status`` gives for its own month table).
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
_DAY_SPELLINGS: Mapping[str, tuple[re.Pattern[str], Mapping[str, int]]] = MappingProxyType(
    {
        "house": (
            re.compile(r"(?P<day>[0-9]{1,2})-(?P<month>[A-Z][a-z]{2})-(?P<year>[0-9]{4})"),
            {name[:3]: number for number, name in enumerate(_MONTH_NAMES, start=1)},
        ),
        "senate": (
            re.compile(
                r"(?P<month>[A-Z][a-z]+) (?P<day>[0-9]{1,2}), (?P<year>[0-9]{4}),\s+(?:1[0-2]|0?[1-9]):[0-5][0-9] [AP]M"
            ),
            {name: number for number, name in enumerate(_MONTH_NAMES, start=1)},
        ),
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


class VoteMenuIdentityError(VoteSourceError):
    """The menu file's own stated congress/session does not match the (congress, session) requested.

    A menu carries no roll number of its own (it *lists* roll numbers), so
    this is not a ``VoteIdentityError`` -- that error's message and fields
    are shaped around one vote's congress/session/roll triple against a
    ``VoteLocator``. This is the same proof one level up: the file fetched
    for one session is checked against its own stated ``<congress>``/
    ``<session>`` before any of its listed votes are returned.
    """

    def __init__(self, *, requested: tuple[int, int], parsed: tuple[int, int], index: str = "senate vote menu") -> None:
        super().__init__(
            f"{index} fetched for congress={requested[0]} session={requested[1]} "
            f"states a different identity: congress={parsed[0]} session={parsed[1]}"
        )
        self.requested = requested
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
    """The Clerk EVS calendar year for one session, by the fixed post-20th-Amendment calendar (74th Congress on)."""
    if congress < _EARLIEST_FIXED_CALENDAR_CONGRESS:
        raise VoteSourceError(
            f"congress {congress} predates the fixed session calendar (74th Congress, 1935); "
            "the Clerk's EVS archive never reaches this far (measured floor: 1990, the 101st Congress)"
        )
    if session not in (1, 2):
        raise VoteSourceError("session must be 1 or 2 to build a Clerk EVS url")
    return _FIRST_SESSION_YEAR + 2 * (congress - 1) + (session - 1)


def clerk_url(locator: VoteLocator) -> str:
    """Build the Clerk EVS url; see ``_clerk_year`` for the year<->(congress, session) rule.

    The roll number is zero-padded to three digits (``roll050.xml``); ``:03d``
    is a minimum width, not a truncation, so a roll past 999 still prints in
    full.
    """
    if locator.chamber != "house":
        raise VoteSourceError("clerk_url requires a 'house' locator")
    year = _clerk_year(locator.congress, locator.session)
    return f"https://clerk.house.gov/evs/{year}/roll{locator.roll_number:03d}.xml"


def senate_url(locator: VoteLocator) -> str:
    """Build the Senate LIS url; congress, session and roll number all appear in it directly.

    The congress is zero-padded to three digits, matching ``SENATE_URL_RE``;
    the LIS archive's measured floor is the 101st Congress, so this raises
    rather than building an unmeasured two-digit-congress url.
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


def _check_congress_session(congress: int, session: int) -> None:
    """The menu's own (chamber-less) congress/session shape, reusing ``VoteKey``'s rule via ``_as_vote_key``.

    Every call site here is Senate-only and carries no roll number of its own,
    so both are supplied as fixed, always-valid placeholders purely to reach
    the shared check; ``VoteMatchError``'s message names ``congress``/``session``
    by field, so nothing here leaks the placeholder chamber or roll number.
    """
    _as_vote_key("senate", congress, session, 0)


def senate_vote_menu_url(congress: int, session: int) -> str:
    """Build the Senate LIS vote-menu url for one session: the index ``list_senate_votes`` reads.

    Same three-digit congress, bare session number and 101st-Congress floor as
    ``senate_url``.
    """
    _check_congress_session(congress, session)
    if congress < _EARLIEST_SENATE_CONGRESS:
        raise VoteSourceError(
            f"congress {congress} predates the Senate LIS archive (measured floor: the 101st Congress)"
        )
    return f"https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress:03d}_{session}.xml"


def clerk_vote_index_url(congress: int, session: int, page: str = "index.asp") -> str:
    """Build one Clerk EVS session-index page url: ``index.asp`` or a page it links (``ROLL_100.asp``).

    The year comes from ``_clerk_year``, the rule ``clerk_url`` uses for a vote
    file in the same directory.
    """
    _check_congress_session(congress, session)
    if page != "index.asp" and not _CLERK_INDEX_PAGE_RE.fullmatch(page):
        raise VoteSourceError(f"{page!r} is not a Clerk EVS index page")
    return f"https://clerk.house.gov/evs/{_clerk_year(congress, session)}/{page}"


def locator_from_recorded_vote_url(url: str) -> VoteLocator:
    """Parse a `recordedVotes[].url` back to a locator.

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


def vote_day(chamber: str, literal: str | None) -> str | None:
    """The chamber's own printed vote date as an ISO day (``YYYY-MM-DD``); ``None`` when the file prints none.

    The day is the one the chamber voted on, in Eastern local time, so it sorts
    chronologically where the literal does not (``'10-Jan-2025'`` sorts before
    ``'9-Sep-2024'``). It is not the day of the UTC instant Congress.gov's
    ``recordedVotes`` reference states, which runs a day ahead for an evening
    vote. A printed date in any other spelling refuses (``VoteSourceError``, a
    ``ValueError``) rather than guessing a day.
    """
    spelling = _DAY_SPELLINGS.get(chamber)
    if spelling is None:
        raise VoteSourceError(f"chamber must be 'house' or 'senate', got {chamber!r}")
    text = (literal or "").strip()
    if not text:
        return None
    pattern, months = spelling
    match = pattern.fullmatch(text)
    month = months.get(match["month"]) if match else None
    if match is not None and month is not None:
        with suppress(ValueError):  # a day its month does not have (``29-Feb-2025``) refuses below
            return date(int(match["year"]), month, int(match["day"])).isoformat()
    raise VoteSourceError(f"{chamber} vote date {literal!r} is not the chamber's own spelling")


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
    vote_normalized: NormalizedVote | None

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
    breakdown the totals-by-vote row summarizes. A Clerk candidate election
    instead keeps every literal candidate label and count in ``tallies`` and
    sets ``tally_kind="candidates"``; its named member choices have no ordinary
    normalized position. ``date`` is the publisher's literal and ``day`` its
    ISO reading (``vote_day``); a record whose ``date`` cannot be read refuses
    at construction, so every parsed vote either states a day or states none.
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

    # Candidate elections carry named choices, not yea/nay counts.
    tally_kind: Literal["positions", "candidates"] = "positions"
    # Senate en-bloc votes name multiple documents, kept in publisher order.
    # ``document`` remains populated only for an unambiguous single document.
    documents: tuple[VoteDocument, ...] = ()
    amendments: tuple[VoteAmendment, ...] = ()

    def __post_init__(self) -> None:
        vote_day(self.chamber, self.date)

    @property
    def day(self) -> str | None:
        return vote_day(self.chamber, self.date)

    def vote_key(self) -> VoteKey:
        return _as_vote_key(self.chamber, self.congress, self.session, self.roll_number)


@dataclass(frozen=True, slots=True)
class SenateVoteMenuMatter:
    """One ``<matter>`` row inside a menu vote's ``<en_bloc>`` batch: one item's own issue/question/result."""

    issue: str
    question: str
    result: str


@dataclass(frozen=True, slots=True)
class SenateVoteMenuEntry:
    """One ``<vote>`` row from the Senate LIS vote menu, every field it states, as spelled.

    ``vote_date`` is a bare day-month the publisher states with no year of its
    own (``"18-Dec"``); ``SenateVoteMenu.congress_year`` is only
    *presumptively* that vote's year, not a fact this record states -- a
    session can run into the following January before it adjourns -- so a
    caller building an instant from ``vote_date`` must account for that
    year-boundary case itself.

    ``issue``/``question``/``result`` are ``None`` and ``matters`` is non-empty
    on the roughly 1-in-70 "en_bloc" batch confirmation votes (measured: 9 of
    659, 119th Congress 1st session), because the menu states no single
    issue/question/result for the vote as a whole there, only per-item rows.
    ``question_measure`` is the nested ``<measure>`` some amendment votes carry
    (measured 113 of the 650 non-en_bloc votes); it refuses if the
    ``<question>`` carries any text after ``</measure>``, an unmeasured shape
    this module has no rule for keeping. ``tallies`` keeps the menu's own
    count names (``yeas``, ``nays``) -- the menu states no
    ``present``/``absent``, unlike the vote file itself.
    """

    vote_number: int
    vote_date: str
    issue: str | None
    question: str | None
    question_measure: str | None
    result: str | None
    tallies: Mapping[str, int]
    title: str
    matters: tuple[SenateVoteMenuMatter, ...] = ()


@dataclass(frozen=True, slots=True)
class SenateVoteMenu:
    """One session's Senate roll-call index, in the publisher's own (newest-vote-first) order.

    ``congress``/``session`` are the file's own stated identity, already
    checked against what ``parse_senate_vote_menu`` was asked for;
    ``congress_year`` is the calendar year the menu states beside them.
    """

    congress: int
    session: int
    congress_year: int
    votes: tuple[SenateVoteMenuEntry, ...]


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


def _read_clerk_member(element: Element, label: str, *, candidate_labels: frozenset[str] | None = None) -> MemberVote:
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
    if candidate_labels is None:
        normalized = normalize_vote(vote_text)
    else:
        if vote_text not in candidate_labels:
            raise VoteSourceError(f"{label} member choice {vote_text!r} is absent from candidate totals")
        normalized = _VOTE_NORMALIZATION.get(" ".join(vote_text.split()).casefold())
    return MemberVote(
        bioguide_id=bioguide_id,
        lis_id=None,
        name=name,
        party=party,
        state=state,
        vote=vote_text,
        vote_normalized=normalized,
        sort_field=legislator.get("sort-field"),
        unaccented_name=legislator.get("unaccented-name"),
        role=legislator.get("role"),
    )


def parse_clerk_vote(body: bytes, locator: VoteLocator) -> RollCallVote:
    """Read one House Clerk EVS roll-call file (``<rollcall-vote>``) whole; every field it states is kept.

    Byte-bounding happens at the acquirer (``capture_validated``); called
    directly, the caller's own bytes are the bound. The file's external
    DOCTYPE is tolerated but never resolved.
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
    candidate_elements = totals.findall("totals-by-candidate")
    if totals_by_vote is not None and candidate_elements:
        raise VoteSourceError(f"{label} mixes position and candidate totals")
    candidate_labels: frozenset[str] | None = None
    tally_kind: Literal["positions", "candidates"] = "positions"
    if totals_by_vote is not None:
        tallies = _read_counts(totals_by_vote, _CLERK_COUNT_FIELDS, label)
    elif candidate_elements:
        candidate_counts: dict[str, int] = {}
        for element in candidate_elements:
            candidate = child_text(element, "candidate", error_type=VoteSourceError, label=label)
            if not candidate or candidate in candidate_counts:
                raise VoteSourceError(f"{label} candidate labels must be nonempty and unique")
            count = _required_int(
                child_text(element, "candidate-total", error_type=VoteSourceError, label=label),
                label,
                "candidate-total",
            )
            if count < 0:
                raise VoteSourceError(f"{label} candidate-total must be nonnegative")
            candidate_counts[candidate] = count
        tallies = MappingProxyType(candidate_counts)
        candidate_labels = frozenset(candidate_counts)
        tally_kind = "candidates"
    else:
        raise VoteSourceError(f"{label} is missing <totals-by-vote> or <totals-by-candidate>")

    member_votes = tuple(
        _read_clerk_member(el, label, candidate_labels=candidate_labels) for el in data.findall("recorded-vote")
    )
    if not member_votes:
        raise VoteSourceError(
            f"{label} for congress={congress} session={session} roll={roll_number} lists no recorded votes"
        )

    if candidate_labels is not None:
        observed = Counter(member.vote for member in member_votes)
        if any(observed[candidate] != count for candidate, count in tallies.items()):
            raise VoteSourceError(f"{label} candidate totals disagree with recorded member choices")
        if len({member.bioguide_id for member in member_votes}) != len(member_votes):
            raise VoteSourceError(f"{label} candidate election repeats a member identity")

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
        tally_kind=tally_kind,
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
    (``sources/legislators.py``); an id the crosswalk does not carry resolves
    to ``bioguide_id=None`` rather than refusing the member, since that is a
    real, measured absence (a senator who has just left the current roster),
    not a malformed record.
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

    documents = tuple(_read_document(element, label) for element in root.findall("document"))
    document = documents[0] if len(documents) == 1 else None

    amendments = tuple(_read_amendment(element, label) for element in root.findall("amendment"))
    amendment = amendments[0] if len(amendments) == 1 else None

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
        documents=documents,
        amendment=amendment,
        amendments=amendments,
    )


def _read_menu_matter(element: Element, label: str) -> SenateVoteMenuMatter:
    def text(tag: str) -> str:
        value = child_text(element, tag, error_type=VoteSourceError, label=label)
        if value is None:
            raise VoteSourceError(f"{label} en_bloc matter is missing <{tag}>")
        return value

    return SenateVoteMenuMatter(issue=text("issue"), question=text("question"), result=text("result"))


def _read_menu_entry(element: Element, label: str) -> SenateVoteMenuEntry:
    def required(tag: str) -> str:
        value = child_text(element, tag, error_type=VoteSourceError, label=label)
        if value is None:
            raise VoteSourceError(f"{label} vote is missing <{tag}>")
        return value

    vote_number = _required_int(required("vote_number"), label, "vote_number")
    vote_date = required("vote_date")
    title = required("title")

    tally_element = single_child(element, "vote_tally", error_type=VoteSourceError, label=label)
    if tally_element is None:
        raise VoteSourceError(f"{label} vote {vote_number} is missing <vote_tally>")
    tallies = _read_counts(tally_element, _SENATE_MENU_TALLY_FIELDS, label)

    en_bloc_element = single_child(element, "en_bloc", error_type=VoteSourceError, label=label)
    if en_bloc_element is not None:
        matters = tuple(_read_menu_matter(el, label) for el in en_bloc_element.findall("matter"))
        if not matters:
            raise VoteSourceError(f"{label} vote {vote_number} en_bloc lists no matters")
        issue = question = question_measure = result = None
    else:
        matters = ()
        issue, result = required("issue"), required("result")
        question_element = single_child(element, "question", error_type=VoteSourceError, label=label)
        if question_element is None:
            raise VoteSourceError(f"{label} vote {vote_number} is missing <question>")
        question = (question_element.text or "").strip() or None
        if question is None:
            raise VoteSourceError(f"{label} vote {vote_number} <question> is empty")
        measure_element = single_child(question_element, "measure", error_type=VoteSourceError, label=label)
        question_measure = None
        if measure_element is not None:
            if (measure_element.tail or "").strip():
                # Every measured occurrence (113 of 650 non-en_bloc votes,
                # 119th Congress 1st session) carries no text after
                # </measure>; refuse rather than silently drop text this
                # module has no rule for keeping.
                raise VoteSourceError(f"{label} vote {vote_number} <question> carries text after <measure>")
            question_measure = (measure_element.text or "").strip() or None

    return SenateVoteMenuEntry(
        vote_number=vote_number,
        vote_date=vote_date,
        issue=issue,
        question=question,
        question_measure=question_measure,
        result=result,
        tallies=tallies,
        title=title,
        matters=matters,
    )


def parse_senate_vote_menu(body: bytes, *, congress: int, session: int) -> SenateVoteMenu:
    """Read one Senate LIS vote-menu file (``<vote_summary>``) whole, newest vote first, as published.

    ``congress``/``session`` are the session requested (``list_senate_votes``'s
    own arguments, not a ``VoteLocator`` -- a menu names a session, not one
    roll number); they are checked against the file's own ``<congress>``/
    ``<session>`` before any vote is returned, the same identity-proof shape
    ``parse_clerk_vote``/``parse_senate_vote`` use, raising
    ``VoteMenuIdentityError`` on a mismatch. A well-formed file listing zero
    ``<vote>`` rows is also a refusal, not an empty success.
    """
    _check_congress_session(congress, session)
    label = "Senate LIS vote menu"
    root = parse_xml(body, max_bytes=len(body), error_type=VoteSourceError, label=label)
    if root.tag != "vote_summary":
        raise VoteSourceError(f"{label} root must be <vote_summary>, got <{root.tag}>")

    def text(tag: str) -> str | None:
        return child_text(root, tag, error_type=VoteSourceError, label=label)

    def required(tag: str) -> str:
        value = text(tag)
        if value is None:
            raise VoteSourceError(f"{label} is missing <{tag}>")
        return value

    parsed_congress = _required_int(required("congress"), label, "congress")
    parsed_session = _required_int(required("session"), label, "session")
    if (parsed_congress, parsed_session) != (congress, session):
        raise VoteMenuIdentityError(requested=(congress, session), parsed=(parsed_congress, parsed_session))
    congress_year = _required_int(required("congress_year"), label, "congress_year")

    votes_element = single_child(root, "votes", error_type=VoteSourceError, label=label)
    if votes_element is None:
        raise VoteSourceError(f"{label} is missing <votes>")
    entries = tuple(_read_menu_entry(el, label) for el in votes_element.findall("vote"))
    if not entries:
        raise VoteSourceError(f"{label} for congress={congress} session={session} lists no votes")

    return SenateVoteMenu(congress=parsed_congress, session=parsed_session, congress_year=congress_year, votes=entries)


def locator_from_menu_entry(menu: SenateVoteMenu, entry: SenateVoteMenuEntry) -> VoteLocator:
    """Build the ``VoteLocator`` for one menu row: the menu's own proven congress/session plus its roll number.

    The menu carries no chamber field of its own -- every row on it is a
    Senate vote by construction (the file it came from), so this always
    builds a ``"senate"`` locator.
    """
    if not isinstance(menu, SenateVoteMenu):
        raise TypeError("menu must be a SenateVoteMenu")
    if not isinstance(entry, SenateVoteMenuEntry):
        raise TypeError("entry must be a SenateVoteMenuEntry")
    return VoteLocator("senate", menu.congress, menu.session, entry.vote_number)


@dataclass(frozen=True, slots=True)
class ClerkVoteIndexEntry:
    """One row of the Clerk's EVS session index, every cell it states, as spelled.

    ``vote_date`` is a bare day-month (``"28-Dec"``); the index's year is the
    session's. ``result`` is the Clerk's designator (``P`` passed, ``F``
    failed, ``A`` agreed to, and rarer letters the page does not define). An
    empty cell is ``None``: of the 14,774 measured rows the title is empty on
    575, the issue on 35, the question and result on 5 each; the roll and date
    never are.
    """

    roll_number: int
    vote_date: str
    issue: str | None
    question: str | None
    result: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class ClerkVoteIndexPage:
    """One fetched EVS index page: its own proven session, its rows, and the index pages it links."""

    congress: int
    session: int
    year: int
    votes: tuple[ClerkVoteIndexEntry, ...]
    pages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClerkVoteIndex:
    """One session's House roll calls from the Clerk's own index, newest first, rolls 1..N without a gap."""

    congress: int
    session: int
    year: int
    votes: tuple[ClerkVoteIndexEntry, ...]


class _ClerkIndexHtml(HTMLParser):
    """Collect the heading, each table row's cells (text and first link) and the index-page links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.rows: list[list[tuple[list[str], str | None]]] = []
        self.pages: list[str] = []
        self._heading: list[str] | None = None
        self._row: list[tuple[list[str], str | None]] | None = None
        self._cell: tuple[list[str], str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self._heading = []
        elif tag == "tr":
            self._close_row()
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = ([], None)
            self._row.append(self._cell)
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if _CLERK_INDEX_PAGE_RE.fullmatch(href):
                self.pages.append(href)
            elif self._cell is not None and self._cell[1] is None and self._row is not None:
                self._cell = (self._cell[0], href)
                self._row[-1] = self._cell

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._heading is not None:
            self.headings.append(" ".join("".join(self._heading).split()))
            self._heading = None
        elif tag == "td":
            self._cell = None
        elif tag in ("tr", "table"):
            self._close_row()

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data)
        if self._cell is not None:
            self._cell[0].append(data)

    def close(self) -> None:
        super().close()
        self._close_row()

    def _close_row(self) -> None:
        if self._row:
            self.rows.append(self._row)
        self._row = self._cell = None


def _read_clerk_index_row(row: list[tuple[list[str], str | None]], *, year: int, label: str) -> ClerkVoteIndexEntry:
    if len(row) != _CLERK_INDEX_CELLS:
        raise VoteSourceError(f"{label} row has {len(row)} cells, not the measured {_CLERK_INDEX_CELLS}")
    roll_text, date, issue, question, result, title = (
        joined_text(parts, label=label, bound=_CLERK_INDEX_CELL_BOUND, error_type=VoteSourceError)
        for parts, _href in row
    )
    link = _CLERK_INDEX_VOTE_RE.fullmatch(row[0][1] or "")
    if link is None or int(link["year"]) != year or link["roll"].lstrip("0") != roll_text.lstrip("0"):
        raise VoteSourceError(f"{label} row {roll_text!r} does not link its own {year} roll call")
    if not date:
        raise VoteSourceError(f"{label} roll {roll_text} states no date")
    return ClerkVoteIndexEntry(
        roll_number=int(link["roll"]),
        vote_date=date,
        issue=issue or None,
        question=question or None,
        result=result or None,
        title=title or None,
    )


def parse_clerk_vote_index(body: bytes, *, congress: int, session: int) -> ClerkVoteIndexPage:
    """Read one Clerk EVS index page (``index.asp`` or ``ROLL_*.asp``), its heading proven against the request.

    The heading's congress/session must be the ones requested
    (``VoteMenuIdentityError``) and its year the session's; every row must link
    that year's roll call under the number it prints. A page with neither rows
    nor index links is a refusal, not an empty success.
    """
    _check_congress_session(congress, session)
    label = "Clerk EVS vote index"
    parser = _ClerkIndexHtml()
    text = decode_html_page(body, len(body), label=label, cap=MAX_VOTE_BYTES, error_type=VoteSourceError)
    feed_html(parser, text, label=label, error_type=VoteSourceError)
    headings = [match for heading in parser.headings if (match := _CLERK_INDEX_HEADING_RE.search(heading))]
    if len(headings) != 1:
        raise VoteSourceError(f"{label} states {len(headings)} congress/session headings, not one")
    parsed = (int(headings[0]["congress"]), int(headings[0]["session"]))
    if parsed != (congress, session):
        raise VoteMenuIdentityError(requested=(congress, session), parsed=parsed, index=label)
    year = int(headings[0]["year"])
    if year != _clerk_year(congress, session):
        raise VoteSourceError(f"{label} for congress={congress} session={session} states the year {year}")
    votes = tuple(_read_clerk_index_row(row, year=year, label=label) for row in parser.rows)
    pages = tuple(dict.fromkeys(parser.pages))
    if not votes and not pages:
        raise VoteSourceError(f"{label} for congress={congress} session={session} lists no roll calls")
    return ClerkVoteIndexPage(congress=congress, session=session, year=year, votes=votes, pages=pages)


def assemble_clerk_vote_index(pages: Sequence[ClerkVoteIndexPage]) -> ClerkVoteIndex:
    """One session's complete index from its fetched pages; a later page's row for a roll replaces an earlier one's.

    ``index.asp`` repeats the newest rows its last page also lists, and a vote
    cast between two fetches appears only on the later one. Rolls must run
    1..N: the Clerk numbers each session's roll calls consecutively, so a gap
    means a page was not read whole and is refused rather than published as
    the session's population.
    """
    if not pages:
        raise VoteSourceError("a Clerk EVS vote index needs at least one page")
    first = pages[0]
    identity = (first.congress, first.session, first.year)
    by_roll: dict[int, ClerkVoteIndexEntry] = {}
    for page in pages:
        if (page.congress, page.session, page.year) != identity:
            raise VoteSourceError(
                f"Clerk EVS vote index pages state two sessions: {identity} and {page.congress, page.session, page.year}"
            )
        by_roll.update((entry.roll_number, entry) for entry in page.votes)
    if not by_roll:
        raise VoteSourceError(
            f"Clerk EVS vote index for congress={first.congress} session={first.session} lists no roll calls"
        )
    missing = sorted(set(range(1, max(by_roll) + 1)) - set(by_roll))
    if missing:
        raise VoteSourceError(
            f"Clerk EVS vote index for congress={first.congress} session={first.session} lists rolls up to "
            f"{max(by_roll)} without {len(missing)} of them (first {missing[0]})"
        )
    votes = tuple(by_roll[roll] for roll in sorted(by_roll, reverse=True))
    return ClerkVoteIndex(congress=first.congress, session=first.session, year=first.year, votes=votes)


def locator_from_index_entry(index: ClerkVoteIndex, entry: ClerkVoteIndexEntry) -> VoteLocator:
    """Build the ``VoteLocator`` for one Clerk index row: the index's proven session plus its roll number."""
    if not isinstance(index, ClerkVoteIndex):
        raise TypeError("index must be a ClerkVoteIndex")
    if not isinstance(entry, ClerkVoteIndexEntry):
        raise TypeError("entry must be a ClerkVoteIndexEntry")
    return VoteLocator("house", index.congress, index.session, entry.roll_number)


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


@dataclass(frozen=True, slots=True)
class SenateVoteMenuAcquisition:
    menu: SenateVoteMenu
    capture: CapturedBodyResponse
    request_count: int
    budget: VoteBudget


@dataclass(frozen=True, slots=True)
class ClerkVoteIndexAcquisition:
    """``captures`` are in fetch order, ``index.asp`` first; ``request_count`` totals every page's requests."""

    index: ClerkVoteIndex
    captures: tuple[CapturedBodyResponse, ...]
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

    def list_senate_votes(self, congress: int, session: int) -> SenateVoteMenuAcquisition:
        """Capture one session's Senate LIS vote menu -- the index a votes rollup walks newest first.

        Shares this acquirer's budget, error family and ``named_challenge``
        refusal recasting with ``acquire``; a caller building a ``VoteAcquirer``
        to call both needs a ``VoteBudget.max_bytes`` sized for the larger of
        the two (see ``DEFAULT_MENU_MAX_BYTES``). ``parse_senate_vote_menu``
        proves the file's own congress/session before any row is returned.
        """
        _check_congress_session(congress, session)
        url = senate_vote_menu_url(congress, session)

        def parse(response: CapturedBodyResponse, _allowance: int) -> SenateVoteMenu:
            return parse_senate_vote_menu(response.body, congress=congress, session=session)

        with named_challenge(url, error_type=VoteRefusedError, context_key="vote_acquisition"):
            menu, capture = self.capture_validated(
                url,
                media_types=MEDIA_TYPES,
                parse=parse,
                max_bytes=self.budget.max_bytes,
                unavailable=VoteUnavailableError,
                context={"operation": "senate-vote-menu", "chamber": "senate", "url": url},
            )
        return SenateVoteMenuAcquisition(menu, capture, self.request_count, self.budget)

    def list_house_votes(self, congress: int, session: int) -> ClerkVoteIndexAcquisition:
        """Capture one session's House roll-call index from the Clerk's EVS pages -- ``index.asp`` and each page it links.

        Each page is its own request under this acquirer's budget, so
        ``max_requests`` bounds the retries of one page, not the whole walk;
        ``request_count`` on the result totals them. Every page's heading is
        proven against the request, and ``assemble_clerk_vote_index`` refuses a
        session whose rolls do not run 1..N.
        """
        first = self._capture_clerk_index_page(congress, session, "index.asp")
        fetched = [first, *(self._capture_clerk_index_page(congress, session, name) for name in first[0].pages)]
        pages, captures, requests = zip(*fetched, strict=True)
        return ClerkVoteIndexAcquisition(assemble_clerk_vote_index(pages), captures, sum(requests), self.budget)

    def _capture_clerk_index_page(
        self, congress: int, session: int, name: str
    ) -> tuple[ClerkVoteIndexPage, CapturedBodyResponse, int]:
        url = clerk_vote_index_url(congress, session, name)

        def parse(response: CapturedBodyResponse, _allowance: int) -> ClerkVoteIndexPage:
            return parse_clerk_vote_index(response.body, congress=congress, session=session)

        with named_challenge(url, error_type=VoteRefusedError, context_key="vote_acquisition"):
            page, capture = self.capture_validated(
                url,
                media_types=CLERK_INDEX_MEDIA_TYPES,
                parse=parse,
                max_bytes=self.budget.max_bytes,
                unavailable=VoteUnavailableError,
                context={"operation": "clerk-vote-index", "chamber": "house", "url": url},
            )
        return page, capture, self.request_count


__all__ = [
    "CLERK_INDEX_MEDIA_TYPES",
    "CLERK_URL_RE",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MENU_MAX_BYTES",
    "MAX_VOTE_BYTES",
    "MEDIA_TYPES",
    "SENATE_URL_RE",
    "ClerkVoteIndex",
    "ClerkVoteIndexAcquisition",
    "ClerkVoteIndexEntry",
    "ClerkVoteIndexPage",
    "MemberVote",
    "PartyTotal",
    "RollCallVote",
    "SenateVoteMenu",
    "SenateVoteMenuAcquisition",
    "SenateVoteMenuEntry",
    "SenateVoteMenuMatter",
    "TieBreaker",
    "VoteAcquirer",
    "VoteAcquisition",
    "VoteAmendment",
    "VoteBudget",
    "VoteDocument",
    "VoteIdentityError",
    "VoteLocator",
    "VoteMenuIdentityError",
    "VoteRefusedError",
    "VoteSourceError",
    "VoteUnavailableError",
    "assemble_clerk_vote_index",
    "clerk_url",
    "clerk_vote_index_url",
    "locator_from_index_entry",
    "locator_from_menu_entry",
    "locator_from_recorded_vote_url",
    "normalize_vote",
    "parse_clerk_vote",
    "parse_clerk_vote_index",
    "parse_senate_vote",
    "parse_senate_vote_menu",
    "senate_url",
    "senate_vote_menu_url",
    "vote_day",
]
