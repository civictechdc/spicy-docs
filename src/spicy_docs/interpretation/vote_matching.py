"""Join a roll-call vote to the bill it was taken on, from structured references only.

Reads the ``recordedVotes`` entries the publisher attaches to a bill's own
actions and the ``legislationType``/``legislationNumber`` fields the House vote
route states for a roll call, and returns a ``VoteMatch`` per vote naming the
bill, the rule that supplied it and the publisher URL the reference carried.
This replaces a regex over prose that made the Senate branch unreachable and
left every Senate vote silently unmatched: a recorded vote sits on the bill's
own action, which *is* the join. The six reference fields are required because
a pass over 20 bills found all six present on all 58 entries across two hosts,
and a malformed entry costs that entry, not the bill:
``recorded_vote_references`` returns what it could read alongside a
``refusals`` tuple naming what it could not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from spicy_docs.sources.congress.bill_status import BILL_TYPES, BillIdentity

RECORDED_VOTE_FIELDS: tuple[str, ...] = ("chamber", "congress", "date", "rollNumber", "sessionNumber", "url")
# The parser's field name for each, so one table drives both spellings.
_SNAKE: Mapping[str, str] = MappingProxyType(
    {
        "chamber": "chamber",
        "congress": "congress",
        "date": "date",
        "rollNumber": "roll_number",
        "sessionNumber": "session_number",
        "url": "url",
    }
)
VOTE_CHAMBERS = frozenset({"house", "senate"})

VOTE_MATCH_RULES: tuple[str, ...] = ("bill_action_recorded_vote", "house_vote_legislation", "unmatched")


class VoteMatchError(ValueError):
    """A reference cannot establish the vote or the bill it names."""


@dataclass(frozen=True, slots=True)
class VoteKey:
    """The publisher's identity for one roll call: congress, chamber, session, roll number."""

    congress: int
    chamber: str
    session: int
    roll_number: int

    def __post_init__(self) -> None:
        for name, value in (("congress", self.congress), ("session", self.session), ("roll", self.roll_number)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise VoteMatchError(f"{name} must be a non-negative integer")
        if self.chamber not in VOTE_CHAMBERS:
            raise VoteMatchError("chamber must be 'house' or 'senate'")


@dataclass(frozen=True, slots=True)
class VoteReference:
    """One structured statement that a roll call belongs to a bill."""

    vote: VoteKey
    bill: BillIdentity
    rule: str
    url: str | None
    date: str | None
    action_index: int | None = None


@dataclass(frozen=True, slots=True)
class VoteMatch:
    """``bill`` is ``None`` and ``rule`` is ``unmatched`` when no reference named this vote."""

    vote: VoteKey
    bill: BillIdentity | None
    rule: str
    url: str | None = None
    date: str | None = None


@dataclass(frozen=True, slots=True)
class VoteIndex:
    """First reference wins per vote; a disagreeing later one is kept as a conflict, not dropped."""

    by_vote: Mapping[VoteKey, VoteReference]
    conflicts: tuple[tuple[VoteReference, VoteReference], ...]


def _get(record: object, *names: str) -> object:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return None
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise VoteMatchError(f"recorded vote {field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise VoteMatchError(f"recorded vote {field} must be an integer")


def _required_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VoteMatchError(f"recorded vote {field} must be a non-empty string")
    return value


def bill_type_of(legislation_type: object) -> str:
    """Normalize a publisher legislation type (``HR``, ``S.Res.``) to the lowercase vocabulary."""
    if not isinstance(legislation_type, str):
        raise VoteMatchError("legislation type must be a string")
    normalized = "".join(character for character in legislation_type.lower() if character.isalnum())
    if normalized not in BILL_TYPES:
        raise VoteMatchError(f"unsupported legislation type {legislation_type!r}")
    return normalized


def read_vote_key(entry: object) -> VoteKey:
    """Read the four identity fields of a ``recordedVotes`` entry; all are required."""
    values = {field: _get(entry, field, _SNAKE[field]) for field in RECORDED_VOTE_FIELDS}
    return VoteKey(
        congress=_required_int(values["congress"], "congress"),
        chamber=_required_str(values["chamber"], "chamber").strip().lower(),
        session=_required_int(values["sessionNumber"], "sessionNumber"),
        roll_number=_required_int(values["rollNumber"], "rollNumber"),
    )


def read_recorded_vote(entry: object) -> tuple[VoteKey, str, str]:
    """Read all six sealed fields, refusing the entry if any is absent."""
    key = read_vote_key(entry)
    url = _required_str(_get(entry, "url"), "url")
    date = _required_str(_get(entry, "date"), "date")
    return key, url, date


@dataclass(frozen=True, slots=True)
class VoteRefusal:
    """One entry that could not be read, with where it sat and why."""

    action_index: int
    entry_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class RecordedVoteReferences:
    """What could be read, and what could not. Neither hides the other."""

    references: tuple[VoteReference, ...]
    refusals: tuple[VoteRefusal, ...] = ()


def recorded_vote_references(identity: BillIdentity, actions: Iterable[object]) -> RecordedVoteReferences:
    """Every recorded vote a bill's own actions carry, in publisher order.

    The bill is the enclosing document, so the reference needs no matching at
    all: reading it *is* the join. An entry missing one of the six sealed
    fields is refused on its own and named in ``refusals`` while the rest of
    the bill's votes are still returned; a ``recordedVotes`` that is not a
    list at all is a shape error, not one entry's problem, and still raises
    ``VoteMatchError``.
    """
    references: list[VoteReference] = []
    refusals: list[VoteRefusal] = []
    for position, action in enumerate(actions):
        entries = _get(action, "recordedVotes", "recorded_votes")
        if entries is None:
            continue
        if isinstance(entries, str | Mapping) or not isinstance(entries, Iterable):
            raise VoteMatchError("recordedVotes must be a list of entries")
        for entry_index, entry in enumerate(entries):
            try:
                key, url, date = read_recorded_vote(entry)
            except VoteMatchError as refusal:
                refusals.append(VoteRefusal(position, entry_index, str(refusal)))
                continue
            references.append(
                VoteReference(
                    vote=key,
                    bill=identity,
                    rule="bill_action_recorded_vote",
                    url=url,
                    date=date,
                    action_index=position,
                )
            )
    return RecordedVoteReferences(tuple(references), tuple(refusals))


def house_vote_references(votes: Iterable[object]) -> tuple[VoteReference, ...]:
    """Read ``legislationType``/``legislationNumber`` off House vote records.

    A House vote that names no legislation -- a procedural roll call, an
    adjournment -- is skipped rather than refused: the absence is the
    publisher's answer, not a malformed record.
    """
    references: list[VoteReference] = []
    for vote in votes:
        legislation_type = _get(vote, "legislationType", "legislation_type")
        legislation_number = _get(vote, "legislationNumber", "legislation_number")
        if legislation_type is None or legislation_number is None:
            continue
        congress = _required_int(_get(vote, "congress"), "congress")
        url = _get(vote, "sourceDataURL", "source_data_url")
        date = _get(vote, "startDate", "start_date", "date")
        references.append(
            VoteReference(
                vote=VoteKey(
                    congress=congress,
                    chamber="house",
                    session=_required_int(_get(vote, "sessionNumber", "session_number", "session"), "sessionNumber"),
                    roll_number=_required_int(
                        _get(vote, "rollCallNumber", "roll_call_number", "rollNumber"), "rollCallNumber"
                    ),
                ),
                bill=BillIdentity(
                    congress=congress,
                    bill_type=bill_type_of(legislation_type),
                    number=_required_int(legislation_number, "legislationNumber"),
                ),
                rule="house_vote_legislation",
                url=url if isinstance(url, str) else None,
                date=date if isinstance(date, str) else None,
            )
        )
    return tuple(references)


def index_vote_references(references: Iterable[VoteReference]) -> VoteIndex:
    """One pass, O(references); later references that name a different bill become conflicts."""
    by_vote: dict[VoteKey, VoteReference] = {}
    conflicts: list[tuple[VoteReference, VoteReference]] = []
    for reference in references:
        held = by_vote.get(reference.vote)
        if held is None:
            by_vote[reference.vote] = reference
        elif held.bill != reference.bill:
            conflicts.append((held, reference))
    return VoteIndex(by_vote=by_vote, conflicts=tuple(conflicts))


def match_votes(votes: Iterable[VoteKey], index: VoteIndex) -> tuple[VoteMatch, ...]:
    """Look each vote up by its publisher identity; O(votes) with no regular expressions."""
    matches: list[VoteMatch] = []
    for vote in votes:
        reference = index.by_vote.get(vote)
        if reference is None:
            matches.append(VoteMatch(vote, None, "unmatched"))
        else:
            matches.append(VoteMatch(vote, reference.bill, reference.rule, reference.url, reference.date))
    return tuple(matches)


__all__ = [
    "RECORDED_VOTE_FIELDS",
    "VOTE_CHAMBERS",
    "VOTE_MATCH_RULES",
    "RecordedVoteReferences",
    "VoteIndex",
    "VoteKey",
    "VoteMatch",
    "VoteMatchError",
    "VoteReference",
    "VoteRefusal",
    "bill_type_of",
    "house_vote_references",
    "index_vote_references",
    "match_votes",
    "read_recorded_vote",
    "read_vote_key",
    "recorded_vote_references",
]
